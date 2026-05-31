"""ACL-aware retrieval over the RAG store (ADR-0013 §2).

The non-negotiable: a query must never surface content the caller can't
already see. Because the chunks live in a SEPARATE database from the app
tables, we can't apply the app's visibility WHERE-clause directly. Instead
we resolve the caller into the concrete set of **document ids** they may see
— reusing the PROVEN app-DB helpers (`_visible_properties_stmt` +
`_document_visibility_filter`), no logic re-implemented — and filter
`rag_chunks` by that set BEFORE the vector search. VERWALTER → the whole org.

The cross-user red-team test (test_rag_retrieval.py) is the guard on this
boundary and is MVP-blocking.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# NOTE: these visibility helpers live in the me router today; promoting them
# to app/services/access.py (next to active_contract_filter) is a tracked
# follow-up. Importing them here reuses the exact, tested ACL code.
from app.api.v1.me import _document_visibility_filter, _visible_properties_stmt
from app.models.contact import Contact
from app.models.document import Document
from app.models.etv import EtvAssembly
from app.models.user import User, UserRole
from app.rag.masterdata import contact_doc_id, etv_doc_id
from app.rag.models import RagChunk


@dataclass(frozen=True, slots=True)
class CallerScope:
    organization_id: uuid.UUID
    is_verwalter: bool
    # None ⇒ the whole org (VERWALTER). Otherwise the concrete document ids
    # the caller may see; an empty set ⇒ they see nothing.
    visible_document_ids: frozenset[uuid.UUID] | None


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    document_id: uuid.UUID
    chunk_text: str
    page: int | None
    source_kind: str | None
    contact_name: str | None
    issued_date: date | None
    amount: Decimal | None
    similarity: float
    # "document" | "dienstleister" | … — lets the caller (and the SPA) tell a
    # real document (open via download) from a master-data card (deep-link to
    # the entity). For master-data, contact_id/property_id locate that entity.
    source_type: str = "document"
    contact_id: uuid.UUID | None = None
    property_id: uuid.UUID | None = None


async def resolve_caller_scope(app_session: AsyncSession, user: User) -> CallerScope:
    """Resolve which documents a caller may see, reusing the app-DB ACL.

    VERWALTER sees the whole org. Other roles resolve to the document ids in
    their visible properties, narrowed by the per-document unit/contract/
    contact gate — exactly what the documents tab enforces.
    """
    org = user.organization_id
    if user.role == UserRole.VERWALTER:
        return CallerScope(organization_id=org, is_verwalter=True, visible_document_ids=None)
    if user.contact_id_impower is None:
        return CallerScope(org, is_verwalter=False, visible_document_ids=frozenset())

    visible_properties = (await app_session.scalars(_visible_properties_stmt(user))).all()
    visible_property_ids = {prop.id for prop in visible_properties}
    if not visible_property_ids:
        return CallerScope(org, is_verwalter=False, visible_document_ids=frozenset())

    doc_ids: set[uuid.UUID] = set(
        (
            await app_session.scalars(
                select(Document.id).where(
                    Document.organization_id == org,
                    Document.deleted_at.is_(None),
                    Document.property_id.in_(visible_property_ids),
                    _document_visibility_filter(user),
                )
            )
        ).all()
    )

    # ADR-0013 §4: contact cards are PII (sensitivity=high), VERWALTER-only by
    # construction — EXCEPT the data subject may retrieve their OWN. The card's
    # synthetic id is deterministic from (property, the caller's contact), so we
    # admit exactly those ids: another contact's card has a different id, and a
    # Dienstleister card uses a different id prefix — neither can ever match.
    own_contact_id = await app_session.scalar(
        select(Contact.id).where(Contact.impower_id == user.contact_id_impower)
    )
    if own_contact_id is not None:
        doc_ids.update(contact_doc_id(pid, own_contact_id) for pid in visible_property_ids)

    # ETV cards (ADR-0013 §4) are visible to every member of the property —
    # same as the portal ETV tab and the property-wide invitation/protocol
    # documents. Admit each visible property's assembly cards by their
    # synthetic id (one query for all visible properties).
    assembly_rows = (
        await app_session.execute(
            select(EtvAssembly.property_id, EtvAssembly.id).where(
                EtvAssembly.property_id.in_(visible_property_ids),
                EtvAssembly.deleted_at.is_(None),
            )
        )
    ).all()
    doc_ids.update(etv_doc_id(pid, aid) for pid, aid in assembly_rows)

    return CallerScope(org, is_verwalter=False, visible_document_ids=frozenset(doc_ids))


async def retrieve(
    rag_session: AsyncSession,
    *,
    scope: CallerScope,
    query_embedding: list[float],
    top_k: int = 8,
    min_similarity: float = 0.35,
    property_id: uuid.UUID | None = None,
    issued_year: int | None = None,
    kind: str | None = None,
    contact_query: str | None = None,
) -> list[RetrievedChunk]:
    """Hybrid retrieval: the §2 ACL pre-filter (applied BEFORE the vector
    search) + cosine ANN. Returns up to ``top_k`` permitted chunks with
    cosine similarity ≥ ``min_similarity``, highest first. An empty list is
    the caller's cue to abstain ("nothing found") rather than guess.
    """
    # Hard ACL gate. A non-VERWALTER with no visible documents sees nothing —
    # short-circuit so we never run an unfiltered vector search.
    if not scope.is_verwalter and not scope.visible_document_ids:
        return []

    distance = RagChunk.embedding.cosine_distance(query_embedding)
    stmt = select(RagChunk, distance.label("distance")).where(
        RagChunk.organization_id == scope.organization_id
    )
    if not scope.is_verwalter:
        # Non-empty here (guarded above); the assert narrows it for the type
        # checker and documents the invariant.
        assert scope.visible_document_ids is not None
        stmt = stmt.where(RagChunk.document_id.in_(scope.visible_document_ids))

    # Property scope from the UI's property switcher: when the caller has a
    # property selected, look ONLY in that property's documents/cards. ANDed
    # with the ACL filter above, so it can only narrow what's already visible —
    # never widen it. (Org-level chunks with no property_id are excluded while a
    # property is selected, which matches "only the selected property's docs".)
    if property_id is not None:
        stmt = stmt.where(RagChunk.property_id == property_id)

    # Structured metadata pre-filter — the "hybrid" half (ADR-0013 §3),
    # applied BEFORE the ANN so vendor/date/kind narrow the candidate set.
    # The generation layer (#146) populates these from the parsed query.
    if issued_year is not None:
        stmt = stmt.where(RagChunk.issued_year == issued_year)
    if kind is not None:
        stmt = stmt.where(RagChunk.source_kind == kind)
    if contact_query:
        stmt = stmt.where(RagChunk.contact_name.ilike(f"%{contact_query}%"))

    stmt = stmt.order_by(distance).limit(top_k)

    results: list[RetrievedChunk] = []
    for chunk, dist in (await rag_session.execute(stmt)).all():
        similarity = 1.0 - float(dist)
        if similarity < min_similarity:
            continue
        results.append(
            RetrievedChunk(
                document_id=chunk.document_id,
                chunk_text=chunk.chunk_text,
                page=chunk.page,
                source_kind=chunk.source_kind,
                contact_name=chunk.contact_name,
                issued_date=chunk.issued_date,
                amount=chunk.amount,
                similarity=similarity,
                source_type=chunk.source_type,
                contact_id=chunk.contact_id,
                property_id=chunk.property_id,
            )
        )
    return results
