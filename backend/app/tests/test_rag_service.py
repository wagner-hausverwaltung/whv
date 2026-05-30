"""Tests for the app-DB → RAG store bridge (ADR-0013 §3): label resolution
(pure) + reindex_document (app DB via factories + the live pgvector store,
with a fake bytes-fetch + embedder so no I/O or Google calls happen).
"""

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.models.contact import Contact, ContactKind
from app.models.document import Document, DocumentKind, DocumentVisibility
from app.models.property import Property, PropertyState, PropertyType
from app.rag.constants import EMBEDDING_DIM
from app.rag.models import RagChunk
from app.rag.service import _contact_label, _property_label, reindex_document
from app.tests._factories import make_document, make_org, make_property


def _pdf(text: str) -> bytes:
    buf = BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    pdf.drawString(72, 750, text)
    pdf.showPage()
    pdf.save()
    return buf.getvalue()


class FakeEmbedder:
    async def embed_texts(
        self, texts: Sequence[str], *, task_type: str = "retrieval_document"
    ) -> list[list[float]]:
        return [[0.001 * (i + 1)] * EMBEDDING_DIM for i in range(len(texts))]


# --- pure label resolution --------------------------------------------------


def test_contact_label_company() -> None:
    contact = Contact(
        organization_id=uuid.uuid4(), kind=ContactKind.COMPANY, company_name="Mustermann GmbH"
    )
    assert _contact_label(contact) == "Mustermann GmbH"


def test_contact_label_person() -> None:
    contact = Contact(
        organization_id=uuid.uuid4(),
        kind=ContactKind.PERSON,
        first_name="Anna",
        last_name="Schmidt",
    )
    assert _contact_label(contact) == "Anna Schmidt"


def test_contact_label_none() -> None:
    assert _contact_label(None) is None


def test_property_label() -> None:
    prop = Property(
        organization_id=uuid.uuid4(),
        name="Schmidener Str. 32",
        type=PropertyType.STRATA,
        state=PropertyState.READY,
    )
    assert _property_label(prop) == "Schmidener Str. 32"
    assert _property_label(None) is None


# --- reindex_document (integration) -----------------------------------------


async def test_reindex_document_resolves_labels_and_persists(
    test_engine: AsyncEngine, session: AsyncSession, rag_session: AsyncSession
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org, name="Schmidener Str. 32")
    sessionmaker = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sessionmaker() as setup:
        contact = Contact(
            organization_id=org.id, kind=ContactKind.COMPANY, company_name="Mustermann GmbH"
        )
        setup.add(contact)
        await setup.flush()
        doc = Document(
            organization_id=org.id,
            property_id=prop.id,
            contact_id=contact.id,
            name="Heizungswartung",
            kind=DocumentKind.RECHNUNG,
            visibility=DocumentVisibility.OWNERS,
            amount=Decimal("4812.00"),
            issued_date=date(2025, 3, 14),
        )
        setup.add(doc)
        await setup.commit()
        await setup.refresh(doc)
    doc_id = doc.id

    pdf = _pdf("Rechnung Heizungswartung Leistung erbracht")

    async def fake_fetch(_doc: Document, _settings: Settings) -> bytes | None:
        return pdf

    result = await reindex_document(
        session,
        rag_session,
        FakeEmbedder(),
        document_id=doc_id,
        settings=get_settings(),
        fetch_bytes=fake_fetch,
    )

    assert result is not None and not result.skipped
    rows = (
        (await rag_session.execute(select(RagChunk).where(RagChunk.document_id == doc_id)))
        .scalars()
        .all()
    )
    assert rows
    assert all(r.organization_id == org.id and r.property_id == prop.id for r in rows)
    assert all(r.visibility == "OWNERS" and r.source_kind == "RECHNUNG" for r in rows)
    # resolved labels + the authoritative amount landed in the searchable header
    indexed_text = " ".join(r.chunk_text for r in rows)
    assert "Mustermann GmbH" in indexed_text
    assert "Schmidener Str. 32" in indexed_text
    assert "4.812,00" in indexed_text


async def test_reindex_document_missing_returns_none(
    session: AsyncSession, rag_session: AsyncSession
) -> None:
    result = await reindex_document(
        session,
        rag_session,
        FakeEmbedder(),
        document_id=uuid.uuid4(),
        settings=get_settings(),
    )
    assert result is None


async def test_reindex_document_no_bytes_returns_none(
    test_engine: AsyncEngine, session: AsyncSession, rag_session: AsyncSession
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    doc = await make_document(test_engine, org=org, prop=prop, kind=DocumentKind.SONSTIGES)

    async def no_bytes(_doc: Document, _settings: Settings) -> bytes | None:
        return None

    result = await reindex_document(
        session,
        rag_session,
        FakeEmbedder(),
        document_id=doc.id,
        settings=get_settings(),
        fetch_bytes=no_bytes,
    )
    assert result is None
