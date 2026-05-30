"""App-DB → RAG store bridge (ADR-0013 §3).

Resolves a Document into a DocumentMeta (labels for the German metadata
header), sources its PDF bytes (local-disk cache → Impower on demand,
mirroring the admin download endpoint), and indexes it. The pure
``app.rag.ingestion`` core stays free of ORM-loading + I/O; this layer owns
both.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.integrations.storage.documents import document_path
from app.models.contact import Contact, ContactKind
from app.models.document import Document
from app.models.property import Property
from app.rag.ingestion import DocumentMeta, Embedder, IndexResult, index_document
from app.rag.models import RagDocument

logger = logging.getLogger(__name__)


def _contact_label(contact: Contact | None) -> str | None:
    """A human label for the metadata header: company name for companies,
    else "First Last", falling back to the recipient name."""
    if contact is None:
        return None
    if contact.kind == ContactKind.COMPANY and contact.company_name:
        return contact.company_name
    person = " ".join(p for p in (contact.first_name, contact.last_name) if p).strip()
    return person or contact.company_name or contact.recipient_name


def _property_label(prop: Property | None) -> str | None:
    """The property's display name, else its street address."""
    if prop is None:
        return None
    if prop.name:
        return prop.name
    address = " ".join(p for p in (prop.street, prop.number) if p).strip()
    return address or None


async def fetch_document_bytes(doc: Document, settings: Settings) -> bytes | None:
    """Source a Document's PDF bytes: local-disk cache first, then Impower on
    demand. Mirrors the admin download endpoint. Returns None when neither
    yields bytes (the indexer then skips the document)."""
    if doc.storage_url and doc.storage_url.startswith("local-disk:"):
        suffix = doc.storage_url[len("local-disk:") :]
        path = document_path(doc.id, suffix)
        if path.exists():
            try:
                return path.read_bytes()
            except OSError:
                logger.exception("rag: failed to read local document %s", path)

    if doc.impower_id is None or not settings.impower_api_token:
        return None
    # Lazy import keeps the Impower client off the hot import path.
    from app.integrations.impower.client import ImpowerClient

    async with ImpowerClient(settings.impower_api_base, settings.impower_api_token) as client:
        return await client.download_document_content(int(doc.impower_id))


async def build_document_meta(app_session: AsyncSession, doc: Document) -> DocumentMeta:
    """Resolve the §2 ACL scope + the authoritative structured metadata into
    a DocumentMeta. Numbers/dates come straight off the Document (synced from
    Impower), never from OCR."""
    contact_name: str | None = None
    if doc.contact_id is not None:
        contact_name = _contact_label(await app_session.get(Contact, doc.contact_id))
    property_label: str | None = None
    if doc.property_id is not None:
        property_label = _property_label(await app_session.get(Property, doc.property_id))
    return DocumentMeta(
        document_id=doc.id,
        organization_id=doc.organization_id,
        kind=doc.kind,
        visibility=doc.visibility.value,
        sensitivity="normal",
        name=doc.name,
        property_id=doc.property_id,
        unit_id=doc.unit_id,
        contract_id=doc.contract_id,
        contact_id=doc.contact_id,
        contact_name=contact_name,
        property_label=property_label,
        amount=doc.amount,
        issued_date=doc.issued_date,
    )


async def reindex_document(
    app_session: AsyncSession,
    rag_session: AsyncSession,
    embedder: Embedder,
    *,
    document_id: uuid.UUID,
    settings: Settings,
    force: bool = False,
    fetch_bytes: Callable[[Document, Settings], Awaitable[bytes | None]] = fetch_document_bytes,
) -> IndexResult | None:
    """Load a Document, resolve its labels, fetch its bytes, and index it into
    the RAG store. Returns None when the document is gone, soft-deleted, or has
    no fetchable bytes. Flushes the rag_session; the caller commits."""
    doc = await app_session.get(Document, document_id)
    if doc is None or doc.deleted_at is not None:
        return None
    pdf_bytes = await fetch_bytes(doc, settings)
    if pdf_bytes is None:
        logger.info("rag: no fetchable bytes for document %s — skipped", document_id)
        return None
    meta = await build_document_meta(app_session, doc)
    return await index_document(rag_session, embedder, meta=meta, pdf_bytes=pdf_bytes, force=force)


async def enqueue_document_indexing(
    app_session: AsyncSession,
    rag_session: AsyncSession,
    *,
    settings: Settings,
    only_new: bool = True,
    property_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> int:
    """Enqueue ``index_rag_document`` for every Document with a fetchable
    source (an Impower id or a local file). With ``only_new`` (the default),
    skip documents already present in the RAG store — so the nightly post-sync
    hook only indexes genuinely-new docs and doesn't re-download the whole
    corpus. Returns the count enqueued; a no-op returning 0 when rag is off.
    """
    if not settings.rag_enabled:
        return 0

    stmt = select(Document.id).where(
        Document.deleted_at.is_(None),
        or_(Document.impower_id.is_not(None), Document.storage_url.is_not(None)),
    )
    if property_id is not None:
        stmt = stmt.where(Document.property_id == property_id)
    document_ids = list((await app_session.scalars(stmt)).all())

    if only_new:
        indexed = set((await rag_session.scalars(select(RagDocument.document_id))).all())
        document_ids = [doc_id for doc_id in document_ids if doc_id not in indexed]
    if limit is not None:
        document_ids = document_ids[:limit]

    # Lazy import avoids an import cycle (tasks imports this module).
    from app.workers.tasks import index_rag_document

    for doc_id in document_ids:
        index_rag_document.delay(str(doc_id))
    return len(document_ids)
