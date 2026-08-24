"""RAG ingestion orchestration (ADR-0013 §3).

Ties the building blocks together: extract a document's text, prepend the
German metadata header, chunk, embed, and persist into the pgvector store
with the §2 ACL scope columns + the copied-down filterable metadata. Drives
incremental re-indexing off ``content_hash`` so a re-sync only re-embeds
changed documents.

``index_document`` operates inside the caller's transaction (it flushes but
does NOT commit) — the Celery task / service that owns the unit of work
commits. This keeps it composable and lets tests roll back.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentKind
from app.rag.chunking import Chunk, chunk_pages
from app.rag.constants import EMBEDDING_DIM
from app.rag.extraction import ExtractionResult, extract_pdf, scrub_text
from app.rag.metadata import build_metadata_header
from app.rag.models import RagChunk, RagDocument


class IngestionError(RuntimeError):
    """Raised when the embedder returns the wrong count or dimensionality —
    persisting those would corrupt retrieval, so fail loud instead."""


class Embedder(Protocol):
    """The slice of the LLM provider that ingestion needs. Narrower than
    LLMProvider so the orchestration (and its tests) don't depend on the
    generation surface."""

    async def embed_texts(
        self, texts: Sequence[str], *, task_type: str = "retrieval_document"
    ) -> list[list[float]]: ...


@dataclass(frozen=True, slots=True)
class DocumentMeta:
    """Everything ingestion needs about a source Document — the §2 ACL
    scope, plus the authoritative structured metadata (from Impower, never
    OCR). The app-DB resolution layer builds this; ``index_document`` stays
    free of ORM-loading concerns."""

    document_id: uuid.UUID
    organization_id: uuid.UUID
    kind: DocumentKind
    visibility: str
    sensitivity: str = "normal"
    name: str | None = None
    property_id: uuid.UUID | None = None
    unit_id: uuid.UUID | None = None
    contract_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    contact_name: str | None = None
    property_label: str | None = None
    amount: Decimal | None = None
    issued_date: date | None = None


@dataclass(frozen=True, slots=True)
class IndexResult:
    document_id: uuid.UUID
    chunk_count: int
    skipped: bool
    ocr_engine: str


def content_hash(pdf_bytes: bytes) -> str:
    """Stable SHA-256 of the source bytes — drives incremental re-index."""
    return hashlib.sha256(pdf_bytes).hexdigest()


def build_chunks(meta: DocumentMeta, pdf_bytes: bytes) -> tuple[ExtractionResult, list[Chunk]]:
    """Extract text, prepend the synthesised German metadata header to the
    first page (so it leads the first chunk + is itself searchable), and
    chunk. Pure — no DB, no embedding."""
    extraction = extract_pdf(pdf_bytes)
    header = build_metadata_header(
        kind=meta.kind,
        name=meta.name,
        contact_name=meta.contact_name,
        amount=meta.amount,
        issued_date=meta.issued_date,
        property_label=meta.property_label,
    )
    pages = list(extraction.pages)
    if pages:
        pages[0] = f"{header}\n\n{pages[0]}" if pages[0] else header
    else:
        pages = [header]
    return extraction, chunk_pages(pages)


async def index_document(
    rag_session: AsyncSession,
    embedder: Embedder,
    *,
    meta: DocumentMeta,
    pdf_bytes: bytes,
    force: bool = False,
) -> IndexResult:
    """Index one document into the RAG store. Skips re-embedding when the
    content hash is unchanged (unless ``force``). Replaces any prior rows
    for the document. Flushes; the caller commits."""
    digest = content_hash(pdf_bytes)
    existing = (
        await rag_session.execute(
            select(RagDocument.content_hash).where(RagDocument.document_id == meta.document_id)
        )
    ).scalar_one_or_none()
    if existing is not None and existing == digest and not force:
        return IndexResult(meta.document_id, chunk_count=0, skipped=True, ocr_engine="")

    extraction, chunks = build_chunks(meta, pdf_bytes)
    texts = [chunk.text for chunk in chunks]
    embeddings = await embedder.embed_texts(texts, task_type="retrieval_document") if texts else []
    if len(embeddings) != len(texts):
        raise IngestionError(f"embedder returned {len(embeddings)} vectors for {len(texts)} chunks")
    for vector in embeddings:
        if len(vector) != EMBEDDING_DIM:
            raise IngestionError(
                f"embedding has dim {len(vector)}, expected {EMBEDDING_DIM} (model/column mismatch)"
            )

    # Replace any prior index rows for this document (no cross-table FK).
    await rag_session.execute(delete(RagChunk).where(RagChunk.document_id == meta.document_id))
    await rag_session.execute(
        delete(RagDocument).where(RagDocument.document_id == meta.document_id)
    )

    issued_year = meta.issued_date.year if meta.issued_date is not None else None
    rag_session.add(
        RagDocument(
            document_id=meta.document_id,
            organization_id=meta.organization_id,
            # Belt and braces: extraction already scrubs, but this is the one
            # place every document text reaches Postgres.
            extracted_text=scrub_text("\n\n".join(extraction.pages)),
            content_hash=digest,
            ocr_engine=extraction.ocr_engine,
            page_count=extraction.page_count,
            source_kind=meta.kind.value,
            amount=meta.amount,
            issued_date=meta.issued_date,
            contact_id=meta.contact_id,
            contact_name=meta.contact_name,
            property_id=meta.property_id,
            unit_id=meta.unit_id,
            visibility=meta.visibility,
            sensitivity=meta.sensitivity,
        )
    )
    for chunk, vector in zip(chunks, embeddings, strict=True):
        rag_session.add(
            RagChunk(
                document_id=meta.document_id,
                organization_id=meta.organization_id,
                property_id=meta.property_id,
                unit_id=meta.unit_id,
                contract_id=meta.contract_id,
                contact_id=meta.contact_id,
                visibility=meta.visibility,
                source_type="document",
                sensitivity=meta.sensitivity,
                chunk_text=scrub_text(chunk.text),
                page=chunk.page,
                embedding=vector,
                source_kind=meta.kind.value,
                amount=meta.amount,
                issued_date=meta.issued_date,
                issued_year=issued_year,
                contact_name=meta.contact_name,
            )
        )
    await rag_session.flush()
    return IndexResult(
        meta.document_id,
        chunk_count=len(chunks),
        skipped=False,
        ocr_engine=extraction.ocr_engine,
    )


async def index_masterdata_card(
    rag_session: AsyncSession,
    embedder: Embedder,
    *,
    document_id: uuid.UUID,
    organization_id: uuid.UUID,
    source_type: str,
    card_text: str,
    contact_id: uuid.UUID | None = None,
    contact_name: str | None = None,
    property_id: uuid.UUID | None = None,
    visibility: str = "ALL",
    sensitivity: str = "normal",
    source_kind: str | None = None,
    force: bool = False,
) -> IndexResult:
    """Index one master-data "card" (ADR-0013 §4) as a single chunk.

    Unlike ``index_document`` there's no PDF to extract — the card is already
    rendered German text (see ``app.rag.masterdata``). We embed it as one
    chunk and persist it under a SYNTHETIC ``document_id`` (deterministic per
    entity) with the §2 ACL scope columns. Skips re-embedding when the card
    text is unchanged (content hash). Flushes; the caller commits.
    """
    digest = content_hash(card_text.encode("utf-8"))
    existing = (
        await rag_session.execute(
            select(RagDocument.content_hash).where(RagDocument.document_id == document_id)
        )
    ).scalar_one_or_none()
    if existing is not None and existing == digest and not force:
        return IndexResult(document_id, chunk_count=0, skipped=True, ocr_engine="")

    embeddings = await embedder.embed_texts([card_text], task_type="retrieval_document")
    if len(embeddings) != 1:
        raise IngestionError(f"embedder returned {len(embeddings)} vectors for 1 card")
    vector = embeddings[0]
    if len(vector) != EMBEDDING_DIM:
        raise IngestionError(
            f"embedding has dim {len(vector)}, expected {EMBEDDING_DIM} (model/column mismatch)"
        )

    # Replace any prior rows for this card (idempotent re-index).
    await rag_session.execute(delete(RagChunk).where(RagChunk.document_id == document_id))
    await rag_session.execute(delete(RagDocument).where(RagDocument.document_id == document_id))

    rag_session.add(
        RagDocument(
            document_id=document_id,
            organization_id=organization_id,
            extracted_text=scrub_text(card_text),
            content_hash=digest,
            ocr_engine="masterdata",
            page_count=None,
            source_kind=source_kind,
            contact_id=contact_id,
            contact_name=contact_name,
            property_id=property_id,
            visibility=visibility,
            sensitivity=sensitivity,
        )
    )
    rag_session.add(
        RagChunk(
            document_id=document_id,
            organization_id=organization_id,
            property_id=property_id,
            contact_id=contact_id,
            visibility=visibility,
            source_type=source_type,
            sensitivity=sensitivity,
            chunk_text=scrub_text(card_text),
            page=None,
            embedding=vector,
            source_kind=source_kind,
            contact_name=contact_name,
        )
    )
    await rag_session.flush()
    return IndexResult(document_id, chunk_count=1, skipped=False, ocr_engine="masterdata")


async def delete_masterdata_card(rag_session: AsyncSession, *, document_id: uuid.UUID) -> None:
    """Purge a synthetic card's rows (chunks + document) from the store. Used
    when the backing entity was deleted — e.g. an anfragen@ inquiry erased for
    DSGVO must take its PII card with it. Flushes; the caller commits."""
    await rag_session.execute(delete(RagChunk).where(RagChunk.document_id == document_id))
    await rag_session.execute(delete(RagDocument).where(RagDocument.document_id == document_id))
    await rag_session.flush()
