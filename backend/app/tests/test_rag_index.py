"""Persist tests for RAG ingestion orchestration (ADR-0013 §3) against a
real pgvector store. Uses a fake embedder (deterministic 768-d vectors) so
no Google API calls happen. Skips when RAG_DATABASE_URL is unset.
"""

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentKind
from app.rag.constants import EMBEDDING_DIM
from app.rag.ingestion import DocumentMeta, index_document
from app.rag.models import RagChunk, RagDocument


def _pdf(text: str) -> bytes:
    buf = BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    pdf.drawString(72, 750, text)
    pdf.showPage()
    pdf.save()
    return buf.getvalue()


class FakeEmbedder:
    """Returns one deterministic EMBEDDING_DIM-length vector per input, and
    records its calls so tests can assert how often embedding ran."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    async def embed_texts(
        self, texts: Sequence[str], *, task_type: str = "retrieval_document"
    ) -> list[list[float]]:
        self.calls.append((list(texts), task_type))
        return [[0.001 * (i + 1)] * EMBEDDING_DIM for i in range(len(texts))]


async def test_index_document_persists_chunks_with_scope(rag_session: AsyncSession) -> None:
    org, prop = uuid.uuid4(), uuid.uuid4()
    meta = DocumentMeta(
        document_id=uuid.uuid4(),
        organization_id=org,
        kind=DocumentKind.RECHNUNG,
        visibility="OWNERS",
        property_id=prop,
        contact_name="Mustermann GmbH",
        amount=Decimal("4812.00"),
        issued_date=date(2025, 3, 14),
        property_label="Schmidener Str. 32",
    )
    embedder = FakeEmbedder()

    result = await index_document(
        rag_session,
        embedder,
        meta=meta,
        pdf_bytes=_pdf("Rechnung Heizungswartung Betrag laut Vertrag"),
    )

    assert not result.skipped
    assert result.chunk_count >= 1
    assert result.ocr_engine == "pdf-text-layer"

    doc_count = (
        await rag_session.execute(
            select(func.count())
            .select_from(RagDocument)
            .where(RagDocument.document_id == meta.document_id)
        )
    ).scalar_one()
    assert doc_count == 1

    rows = (
        (
            await rag_session.execute(
                select(RagChunk).where(RagChunk.document_id == meta.document_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == result.chunk_count
    # every chunk carries the §2 ACL scope + copied-down metadata
    assert all(r.organization_id == org and r.property_id == prop for r in rows)
    assert all(r.visibility == "OWNERS" and r.source_type == "document" for r in rows)
    assert all(r.issued_year == 2025 and r.source_kind == "RECHNUNG" for r in rows)
    # the synthesised German metadata header is in the indexed text
    assert any("Mustermann GmbH" in r.chunk_text for r in rows)
    assert any("4.812,00" in r.chunk_text for r in rows)
    # embeddings persisted at the right dimensionality
    assert all(len(r.embedding) == EMBEDDING_DIM for r in rows)
    assert embedder.calls and embedder.calls[0][1] == "retrieval_document"


async def test_index_document_incremental_skip_and_force(rag_session: AsyncSession) -> None:
    meta = DocumentMeta(
        document_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        kind=DocumentKind.PROTOKOLL,
        visibility="ALL",
    )
    pdf = _pdf("Protokoll der Eigentuemerversammlung 2025 Beschluss gefasst")
    embedder = FakeEmbedder()

    first = await index_document(rag_session, embedder, meta=meta, pdf_bytes=pdf)
    assert not first.skipped and first.chunk_count >= 1

    # identical bytes → skip, no re-embed
    second = await index_document(rag_session, embedder, meta=meta, pdf_bytes=pdf)
    assert second.skipped and second.chunk_count == 0
    assert len(embedder.calls) == 1

    # force → re-embed + replace (not append)
    third = await index_document(rag_session, embedder, meta=meta, pdf_bytes=pdf, force=True)
    assert not third.skipped
    assert len(embedder.calls) == 2
    total = (
        await rag_session.execute(
            select(func.count())
            .select_from(RagChunk)
            .where(RagChunk.document_id == meta.document_id)
        )
    ).scalar_one()
    assert total == third.chunk_count


async def test_index_document_with_nul_bytes_persists(
    rag_session: AsyncSession, monkeypatch: object
) -> None:
    """Regression (prod 2026-08-24): a NUL in the PDF's text layer made the
    INSERT fail with CharacterNotInRepertoireError, so the whole document
    dropped out of the index and the task burned three retries re-embedding."""
    import pytest

    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.setattr(
        "pypdf._page.PageObject.extract_text",
        lambda self: "Jahresabrechnung 2025\x00 Hausgeld 1.234,56 EUR\x00",
    )
    meta = DocumentMeta(
        document_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        kind=DocumentKind.JAHRESABRECHNUNG,
        visibility="OWNERS",
        property_id=uuid.uuid4(),
    )
    result = await index_document(
        rag_session,
        FakeEmbedder(),
        meta=meta,
        pdf_bytes=_pdf("Platzhalter mit genug Text fuer die Textebene"),
    )
    # The commit is what used to explode — not the flush.
    await rag_session.commit()

    assert result.chunk_count >= 1
    stored = (
        await rag_session.execute(
            select(RagDocument.extracted_text).where(RagDocument.document_id == meta.document_id)
        )
    ).scalar_one()
    assert "\x00" not in stored
    assert "Jahresabrechnung 2025" in stored
    chunk = (
        await rag_session.execute(
            select(RagChunk.chunk_text).where(RagChunk.document_id == meta.document_id).limit(1)
        )
    ).scalar_one()
    assert "\x00" not in chunk


async def test_xml_einvoice_is_marked_not_indexable(rag_session: AsyncSession) -> None:
    """Impower serves ZUGFeRD/XRechnung invoices as XML on the same download
    endpoint. They are not PDFs and carry nothing for semantic search, so
    they are recorded as handled — once, with no chunks — instead of failing
    in pypdf on every backfill (prod 2026-08-25: 88 such warnings per run)."""
    from app.rag.ingestion import NOT_PDF_ENGINE

    xml = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b"<rsm:CrossIndustryInvoice><ram:ID>R26/000199</ram:ID></rsm:CrossIndustryInvoice>"
    )
    meta = DocumentMeta(
        document_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        kind=DocumentKind.RECHNUNG,
        visibility="OWNERS",
        property_id=uuid.uuid4(),
    )
    embedder = FakeEmbedder()
    result = await index_document(rag_session, embedder, meta=meta, pdf_bytes=xml)
    await rag_session.commit()

    assert result.skipped is True
    assert result.chunk_count == 0
    assert result.ocr_engine == NOT_PDF_ENGINE
    # No embedding call — the XML never reaches Gemini.
    assert embedder.calls == []
    # Nothing searchable …
    chunks = (
        await rag_session.execute(
            select(func.count())
            .select_from(RagChunk)
            .where(RagChunk.document_id == meta.document_id)
        )
    ).scalar_one()
    assert chunks == 0
    # … but the document counts as handled, so the next backfill skips it.
    engine = (
        await rag_session.execute(
            select(RagDocument.ocr_engine).where(RagDocument.document_id == meta.document_id)
        )
    ).scalar_one()
    assert engine == NOT_PDF_ENGINE


async def test_repeated_xml_index_does_not_re_download_or_embed(rag_session: AsyncSession) -> None:
    """Second pass over the same XML: the unchanged-hash shortcut takes it,
    so the skip really is permanent rather than repeated work."""
    xml = b'<?xml version="1.0"?><Invoice/>'
    meta = DocumentMeta(
        document_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        kind=DocumentKind.RECHNUNG,
        visibility="OWNERS",
    )
    embedder = FakeEmbedder()
    await index_document(rag_session, embedder, meta=meta, pdf_bytes=xml)
    await rag_session.commit()
    second = await index_document(rag_session, embedder, meta=meta, pdf_bytes=xml)
    assert second.skipped is True
    assert embedder.calls == []
