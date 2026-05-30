"""Master-data cards (ADR-0013 §4): card rendering + the VERWALTER-only ACL.

Card rendering + the synthetic-id helper are pure (run always). The
ingestion + retrieval ACL test needs the pgvector store, so it's skipped
unless RAG_DATABASE_URL is set (CI provides it via the `vectordb` service).

The ACL property is the security-critical claim: a master-data card carries a
SYNTHETIC document_id, and a non-VERWALTER's retrieval is gated to their REAL
visible document ids — so a synthetic id is never a member and cards stay
VERWALTER-only, with no change to the ACL filter.
"""

import os
import uuid
from collections.abc import Sequence
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.constants import EMBEDDING_DIM
from app.rag.masterdata import (
    SOURCE_TYPE_DIENSTLEISTER,
    build_dienstleister_card,
    dienstleister_doc_id,
)

_RAG = pytest.mark.skipif(
    not os.getenv("RAG_DATABASE_URL"),
    reason="RAG_DATABASE_URL not set — RAG store tests skipped",
)


def test_build_dienstleister_card_full() -> None:
    card = build_dienstleister_card(
        name="Mustermann GmbH",
        property_label="Schmidener Str. 32",
        invoice_count=7,
        current_year=2025,
        total_amount=Decimal("4812.00"),
        last_service_date="2025-03-14",
        email="info@mustermann.de",
        phone="+49 711 1234567",
        recent_services=["Heizungswartung", "Notdienst"],
    )
    assert card == (
        "Dienstleister: Mustermann GmbH · Objekt: Schmidener Str. 32 · "
        "Rechnungen gesamt: 7 · 2025 Summe: 4.812,00 € · letzte Leistung: 2025-03-14 · "
        "Kontakt: info@mustermann.de, +49 711 1234567 · "
        "Leistungen: Heizungswartung; Notdienst"
    )


def test_build_dienstleister_card_skips_missing() -> None:
    assert build_dienstleister_card(name="Solo Handwerk") == "Dienstleister: Solo Handwerk"


def test_dienstleister_doc_id_deterministic_and_unique() -> None:
    p1, p2 = uuid.uuid4(), uuid.uuid4()
    c1, c2 = uuid.uuid4(), uuid.uuid4()
    assert dienstleister_doc_id(p1, c1) == dienstleister_doc_id(p1, c1)  # stable
    assert dienstleister_doc_id(p1, c1) != dienstleister_doc_id(p1, c2)  # per vendor
    assert dienstleister_doc_id(p1, c1) != dienstleister_doc_id(p2, c1)  # per property


class _StubEmbedder:
    async def embed_texts(
        self, texts: Sequence[str], *, task_type: str = "retrieval_document"
    ) -> list[list[float]]:
        return [[0.1] * EMBEDDING_DIM for _ in texts]


@_RAG
async def test_masterdata_card_is_verwalter_only(rag_session: AsyncSession) -> None:
    from app.rag.ingestion import index_masterdata_card
    from app.rag.retrieval import CallerScope, retrieve

    org = uuid.uuid4()
    prop = uuid.uuid4()
    contact = uuid.uuid4()
    doc_id = dienstleister_doc_id(prop, contact)

    await index_masterdata_card(
        rag_session,
        _StubEmbedder(),
        document_id=doc_id,
        organization_id=org,
        source_type=SOURCE_TYPE_DIENSTLEISTER,
        card_text="Dienstleister: Mustermann GmbH · Gewerk: Heizung",
        contact_id=contact,
        contact_name="Mustermann GmbH",
        property_id=prop,
        source_kind="DIENSTLEISTER",
    )
    await rag_session.flush()

    query = [0.1] * EMBEDDING_DIM

    # VERWALTER (no document-id gate) retrieves the card, with the entity refs
    # the SPA needs to deep-link.
    verwalter = CallerScope(organization_id=org, is_verwalter=True, visible_document_ids=None)
    got = await retrieve(rag_session, scope=verwalter, query_embedding=query, min_similarity=0.0)
    md = next(c for c in got if c.document_id == doc_id)
    assert md.source_type == SOURCE_TYPE_DIENSTLEISTER
    assert md.contact_id == contact
    assert md.property_id == prop

    # A non-VERWALTER whose visible docs are real document ids never matches the
    # synthetic master-data id → cards are invisible to them.
    owner = CallerScope(
        organization_id=org,
        is_verwalter=False,
        visible_document_ids=frozenset({uuid.uuid4()}),
    )
    got_owner = await retrieve(rag_session, scope=owner, query_embedding=query, min_similarity=0.0)
    assert all(c.document_id != doc_id for c in got_owner)
