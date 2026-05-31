"""ACL red-team + abstain tests for RAG retrieval (ADR-0013 §2) — the
MVP-blocking guarantee that a query never surfaces content the caller can't
already see. Runs against the live pgvector store + the app DB factories.
Skips when RAG_DATABASE_URL is unset.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models.document import DocumentKind
from app.models.user import User, UserRole
from app.rag.constants import EMBEDDING_DIM
from app.rag.models import RagChunk
from app.rag.retrieval import resolve_caller_scope, retrieve
from app.tests._factories import (
    make_contact_with_contract_link,
    make_document,
    make_org,
    make_property,
    make_user,
)

_VEC = [0.1] * EMBEDDING_DIM


def _add_chunk(rag_session: AsyncSession, *, document_id, organization_id, vector=_VEC) -> None:  # type: ignore[no-untyped-def]
    rag_session.add(
        RagChunk(
            document_id=document_id,
            organization_id=organization_id,
            visibility="OWNERS",
            chunk_text=f"chunk for {document_id}",
            embedding=vector,
        )
    )


class _StubEmbedder:
    async def embed_texts(
        self, texts: Sequence[str], *, task_type: str = "retrieval_document"
    ) -> list[list[float]]:
        return [list(_VEC) for _ in texts]


async def test_retrieval_blocks_cross_user_and_cross_property(
    test_engine: AsyncEngine, session: AsyncSession, rag_session: AsyncSession
) -> None:
    org_a = await make_org(test_engine)
    org_b = await make_org(test_engine)
    prop1 = await make_property(test_engine, org=org_a, name="P1")
    prop2 = await make_property(test_engine, org=org_a, name="P2")
    prop_b = await make_property(test_engine, org=org_b, name="PB")

    # owner1 is on an active contract for P1 only
    await make_contact_with_contract_link(
        test_engine, org=org_a, prop=prop1, contact_impower_id=5001
    )
    owner1, _e1, _p1 = await make_user(
        test_engine, org=org_a, role=UserRole.EIGENTUEMER, contact_id_impower=5001
    )
    verwalter, _e2, _p2 = await make_user(test_engine, org=org_a, role=UserRole.VERWALTER)

    doc1 = await make_document(test_engine, org=org_a, prop=prop1, kind=DocumentKind.RECHNUNG)
    doc2 = await make_document(test_engine, org=org_a, prop=prop2, kind=DocumentKind.RECHNUNG)
    doc_b = await make_document(test_engine, org=org_b, prop=prop_b, kind=DocumentKind.RECHNUNG)

    _add_chunk(rag_session, document_id=doc1.id, organization_id=org_a.id)
    _add_chunk(rag_session, document_id=doc2.id, organization_id=org_a.id)
    _add_chunk(rag_session, document_id=doc_b.id, organization_id=org_b.id)
    await rag_session.flush()

    # owner1: P1 only — never P2 (other property) or org B (other org)
    scope1 = await resolve_caller_scope(session, owner1)
    got1 = await retrieve(rag_session, scope=scope1, query_embedding=_VEC, min_similarity=0.0)
    assert {c.document_id for c in got1} == {doc1.id}

    # VERWALTER: whole org A (P1 + P2), never org B
    scope_v = await resolve_caller_scope(session, verwalter)
    got_v = await retrieve(rag_session, scope=scope_v, query_embedding=_VEC, min_similarity=0.0)
    assert {c.document_id for c in got_v} == {doc1.id, doc2.id}
    assert doc_b.id not in {c.document_id for c in got_v}


async def test_retrieval_owner_without_access_sees_nothing(
    test_engine: AsyncEngine, session: AsyncSession, rag_session: AsyncSession
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    doc = await make_document(test_engine, org=org, prop=prop, kind=DocumentKind.RECHNUNG)
    _add_chunk(rag_session, document_id=doc.id, organization_id=org.id)
    await rag_session.flush()

    # an owner with no contract for any property (unknown contact_id_impower)
    stranger, _e, _p = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=9999
    )
    scope = await resolve_caller_scope(session, stranger)
    assert scope.visible_document_ids == frozenset()
    got = await retrieve(rag_session, scope=scope, query_embedding=_VEC, min_similarity=0.0)
    assert got == []


async def test_retrieve_abstains_below_similarity_threshold(
    test_engine: AsyncEngine, session: AsyncSession, rag_session: AsyncSession
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    doc = await make_document(test_engine, org=org, prop=prop, kind=DocumentKind.RECHNUNG)
    chunk_vec = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
    query_vec = [0.0, 1.0] + [0.0] * (EMBEDDING_DIM - 2)  # orthogonal → cosine sim 0
    _add_chunk(rag_session, document_id=doc.id, organization_id=org.id, vector=chunk_vec)
    await rag_session.flush()

    verwalter, _e, _p = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    scope = await resolve_caller_scope(session, verwalter)

    # below threshold → abstain
    below = await retrieve(rag_session, scope=scope, query_embedding=query_vec, min_similarity=0.5)
    assert below == []
    # threshold lifted → the chunk comes back
    got = await retrieve(rag_session, scope=scope, query_embedding=query_vec, min_similarity=-1.0)
    assert len(got) == 1 and got[0].document_id == doc.id


async def test_retrieve_hybrid_metadata_filters(
    test_engine: AsyncEngine, session: AsyncSession, rag_session: AsyncSession
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    doc_rechnung = await make_document(test_engine, org=org, prop=prop, kind=DocumentKind.RECHNUNG)
    doc_protokoll = await make_document(
        test_engine, org=org, prop=prop, kind=DocumentKind.PROTOKOLL
    )
    rag_session.add(
        RagChunk(
            document_id=doc_rechnung.id,
            organization_id=org.id,
            visibility="ALL",
            chunk_text="rechnung",
            embedding=_VEC,
            source_kind="RECHNUNG",
            issued_year=2025,
            contact_name="Mustermann GmbH",
        )
    )
    rag_session.add(
        RagChunk(
            document_id=doc_protokoll.id,
            organization_id=org.id,
            visibility="ALL",
            chunk_text="protokoll",
            embedding=_VEC,
            source_kind="PROTOKOLL",
            issued_year=2024,
        )
    )
    await rag_session.flush()

    verwalter, _e, _p = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    scope = await resolve_caller_scope(session, verwalter)

    by_year = await retrieve(
        rag_session, scope=scope, query_embedding=_VEC, min_similarity=0.0, issued_year=2025
    )
    assert {c.document_id for c in by_year} == {doc_rechnung.id}

    by_kind = await retrieve(
        rag_session, scope=scope, query_embedding=_VEC, min_similarity=0.0, kind="PROTOKOLL"
    )
    assert {c.document_id for c in by_kind} == {doc_protokoll.id}

    by_contact = await retrieve(
        rag_session,
        scope=scope,
        query_embedding=_VEC,
        min_similarity=0.0,
        contact_query="mustermann",
    )
    assert {c.document_id for c in by_contact} == {doc_rechnung.id}


async def test_caller_scope_trusts_impower_attribution_for_property_wide_docs(
    test_engine: AsyncEngine, session: AsyncSession
) -> None:
    """ADR-0014 (#153): a document with no owner FK is genuinely WEG-level.

    A prod attribution probe showed Impower scopes individual per-owner
    Abrechnungen with a unit/contract/contact FK; it leaves the FKs empty only
    for whole-WEG aggregates (e.g. the Gesamtabrechnung every owner may see).
    So we TRUST that attribution: a property-wide (all-FKs-NULL) doc — even a
    JAHRESABRECHNUNG — is visible to every owner of the property, while a doc
    scoped to ANOTHER owner's contact stays private to them.

    Asserted on `resolve_caller_scope` (the app-DB ACL that both the documents
    tab and the assistant filter by), so it covers both surfaces and runs
    without the RAG store.
    """
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org, name="ACL-P1")
    # The caller (owner A) and a second, unrelated owner (B) on the same property.
    await make_contact_with_contract_link(test_engine, org=org, prop=prop, contact_impower_id=5101)
    contact_b, _ctr_b = await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=5102
    )
    owner_a, _e, _p = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=5101
    )

    # Property-wide Gesamtabrechnung (no owner FK) — must reach owner A.
    doc_gesamt = await make_document(
        test_engine, org=org, prop=prop, kind=DocumentKind.JAHRESABRECHNUNG
    )
    # Owner B's individual doc (contact-scoped) — must NOT reach owner A.
    doc_b_private = await make_document(
        test_engine, org=org, prop=prop, kind=DocumentKind.JAHRESABRECHNUNG, contact=contact_b
    )

    scope = await resolve_caller_scope(session, owner_a)
    assert scope.visible_document_ids is not None
    assert doc_gesamt.id in scope.visible_document_ids  # trust: WEG-level → shared
    assert doc_b_private.id not in scope.visible_document_ids  # scoped to owner B only


async def test_retrieve_scopes_to_selected_property(
    test_engine: AsyncEngine, session: AsyncSession, rag_session: AsyncSession
) -> None:
    # The UI property switcher → only that property's chunks are searched.
    org = await make_org(test_engine)
    prop1 = await make_property(test_engine, org=org, name="P1")
    prop2 = await make_property(test_engine, org=org, name="P2")
    doc1 = await make_document(test_engine, org=org, prop=prop1, kind=DocumentKind.RECHNUNG)
    doc2 = await make_document(test_engine, org=org, prop=prop2, kind=DocumentKind.RECHNUNG)
    rag_session.add(
        RagChunk(
            document_id=doc1.id,
            organization_id=org.id,
            property_id=prop1.id,
            visibility="ALL",
            chunk_text="p1",
            embedding=_VEC,
        )
    )
    rag_session.add(
        RagChunk(
            document_id=doc2.id,
            organization_id=org.id,
            property_id=prop2.id,
            visibility="ALL",
            chunk_text="p2",
            embedding=_VEC,
        )
    )
    await rag_session.flush()

    verwalter, _e, _p = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    scope = await resolve_caller_scope(session, verwalter)

    # No property scope → both properties' chunks.
    unscoped = await retrieve(rag_session, scope=scope, query_embedding=_VEC, min_similarity=0.0)
    assert {c.document_id for c in unscoped} == {doc1.id, doc2.id}

    # Scoped to P1 → only P1's chunk.
    scoped = await retrieve(
        rag_session, scope=scope, query_embedding=_VEC, min_similarity=0.0, property_id=prop1.id
    )
    assert {c.document_id for c in scoped} == {doc1.id}


async def test_contact_card_visible_to_data_subject_but_not_other_owner(
    test_engine: AsyncEngine, session: AsyncSession, rag_session: AsyncSession
) -> None:
    """ADR-0013 §4: a contact card is PII — VERWALTER-only by construction, plus
    the data subject themselves. Owner A retrieves their OWN contact card; owner
    B (same property) never does; a Dienstleister card stays VERWALTER-only for
    both owners. Verwalter sees both."""
    from app.rag.ingestion import index_masterdata_card
    from app.rag.masterdata import (
        SOURCE_TYPE_CONTACT,
        SOURCE_TYPE_DIENSTLEISTER,
        contact_doc_id,
        dienstleister_doc_id,
    )

    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org, name="MD-P1")
    contact_a, _ca = await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=5201
    )
    await make_contact_with_contract_link(test_engine, org=org, prop=prop, contact_impower_id=5202)
    owner_a, _ea, _pa = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=5201
    )
    owner_b, _eb, _pb = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=5202
    )
    verwalter, _ev, _pv = await make_user(test_engine, org=org, role=UserRole.VERWALTER)

    card_a = contact_doc_id(prop.id, contact_a.id)
    vendor_card = dienstleister_doc_id(prop.id, uuid.uuid4())
    emb = _StubEmbedder()
    await index_masterdata_card(
        rag_session,
        emb,
        document_id=card_a,
        organization_id=org.id,
        source_type=SOURCE_TYPE_CONTACT,
        card_text="Kontakt: Owner A",
        contact_id=contact_a.id,
        contact_name="Owner A",
        property_id=prop.id,
        sensitivity="high",
        source_kind="KONTAKT",
    )
    await index_masterdata_card(
        rag_session,
        emb,
        document_id=vendor_card,
        organization_id=org.id,
        source_type=SOURCE_TYPE_DIENSTLEISTER,
        card_text="Dienstleister: V",
        contact_id=uuid.uuid4(),
        contact_name="V",
        property_id=prop.id,
        source_kind="DIENSTLEISTER",
    )
    await rag_session.flush()

    async def _ids(user: User) -> set[uuid.UUID]:
        scope = await resolve_caller_scope(session, user)
        got = await retrieve(rag_session, scope=scope, query_embedding=_VEC, min_similarity=0.0)
        return {c.document_id for c in got}

    a_ids = await _ids(owner_a)
    assert card_a in a_ids  # data subject sees their own card
    assert vendor_card not in a_ids  # Dienstleister stays VERWALTER-only

    b_ids = await _ids(owner_b)
    assert card_a not in b_ids  # never another owner's contact card
    assert vendor_card not in b_ids

    v_ids = await _ids(verwalter)
    assert {card_a, vendor_card} <= v_ids  # Verwalter sees both
