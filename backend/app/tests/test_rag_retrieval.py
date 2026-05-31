"""ACL red-team + abstain tests for RAG retrieval (ADR-0013 §2) — the
MVP-blocking guarantee that a query never surfaces content the caller can't
already see. Runs against the live pgvector store + the app DB factories.
Skips when RAG_DATABASE_URL is unset.
"""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models.document import Document, DocumentKind
from app.models.user import UserRole
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


async def _set_source_type(engine: AsyncEngine, doc_id, source_type: str) -> None:  # type: ignore[no-untyped-def]
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        doc = await s.get(Document, doc_id)
        assert doc is not None
        doc.impower_source_type = source_type
        await s.commit()


async def test_caller_scope_hides_unattributed_personal_financial_docs(
    test_engine: AsyncEngine, session: AsyncSession
) -> None:
    """#153 / ADR-0014 fail-closed rule. A personal-financial document that
    arrived WITHOUT an owner FK (unit/contract/contact all NULL) must NOT reach
    other members of the property through the 'property-wide' branch — a
    Jahresabrechnung or Sonderumlage contains another owner's PII. Shared
    property-wide docs (Rechnung, plain Sonstiges) stay visible: we close the
    leak without over-hiding. Verwalter still sees everything.

    Asserted on `resolve_caller_scope` (the app-DB ACL that the documents tab
    and the assistant both filter by), so it covers both surfaces and runs
    without the RAG store.
    """
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org, name="ACL-P1")
    await make_contact_with_contract_link(test_engine, org=org, prop=prop, contact_impower_id=5101)
    owner, _e, _p = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=5101
    )
    verwalter, _ev, _pv = await make_user(test_engine, org=org, role=UserRole.VERWALTER)

    # All four are property-wide (no unit/contract/contact FK).
    doc_shared = await make_document(test_engine, org=org, prop=prop, kind=DocumentKind.RECHNUNG)
    doc_plain = await make_document(test_engine, org=org, prop=prop, kind=DocumentKind.SONSTIGES)
    doc_jahres = await make_document(
        test_engine, org=org, prop=prop, kind=DocumentKind.JAHRESABRECHNUNG
    )
    # Sonderumlage lands under SONSTIGES — the source-type branch must catch it.
    doc_sonder = await make_document(test_engine, org=org, prop=prop, kind=DocumentKind.SONSTIGES)
    await _set_source_type(test_engine, doc_sonder.id, "SPECIAL_CONTRIBUTION")

    # Owner: the two shared docs only — never the unattributed personal ones.
    scope = await resolve_caller_scope(session, owner)
    assert scope.visible_document_ids is not None
    assert doc_shared.id in scope.visible_document_ids
    assert doc_plain.id in scope.visible_document_ids
    assert doc_jahres.id not in scope.visible_document_ids
    assert doc_sonder.id not in scope.visible_document_ids

    # Verwalter: all four (the gate is bypassed for VERWALTER).
    scope_v = await resolve_caller_scope(session, verwalter)
    assert scope_v.visible_document_ids is None  # whole org


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
