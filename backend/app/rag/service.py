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
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.integrations.storage.documents import document_path
from app.models.anfrage import OfferInquiry, OfferInquiryStatus
from app.models.contact import Contact, ContactKind
from app.models.contract import Contract, ContractContact, ContractType
from app.models.document import Document
from app.models.etv import (
    AgendaItemType,
    AgendaItemVoteResult,
    AssemblyStatus,
    EtvAgendaItem,
    EtvAssembly,
)
from app.models.property import Property
from app.models.trip import Trip
from app.models.unit import Unit
from app.rag.ingestion import (
    DocumentMeta,
    Embedder,
    IndexResult,
    delete_masterdata_card,
    index_document,
    index_masterdata_card,
)
from app.rag.masterdata import (
    SOURCE_TYPE_ANFRAGE,
    SOURCE_TYPE_CONTACT,
    SOURCE_TYPE_DIENSTLEISTER,
    SOURCE_TYPE_ETV,
    anfrage_doc_id,
    build_anfrage_card,
    build_contact_card,
    build_dienstleister_card,
    build_etv_card,
    contact_doc_id,
    dienstleister_doc_id,
    etv_doc_id,
)
from app.rag.models import RagDocument
from app.services.vendors import load_vendors_for_property

_CONTRACT_ROLE_LABEL: dict[ContractType, str] = {
    ContractType.OWNER: "Eigentümer",
    ContractType.TENANT: "Mieter",
    ContractType.PROPERTY_OWNER: "Eigentümer",
}

_ASSEMBLY_STATUS_LABEL: dict[AssemblyStatus, str] = {
    AssemblyStatus.GEPLANT: "Geplant",
    AssemblyStatus.EINGELADEN: "Eingeladen",
    AssemblyStatus.ABGEHALTEN: "Abgehalten",
    AssemblyStatus.ABGESAGT: "Abgesagt",
}

_VOTE_RESULT_LABEL: dict[AgendaItemVoteResult, str] = {
    AgendaItemVoteResult.ANGENOMMEN: "angenommen",
    AgendaItemVoteResult.ABGELEHNT: "abgelehnt",
}

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


def _unit_label(unit: Unit | None) -> str | None:
    """The unit's human id (e.g. "W3"), else a floor/position hint."""
    if unit is None:
        return None
    if unit.unit_hr_id:
        return unit.unit_hr_id
    return " ".join(p for p in (unit.floor, unit.position) if p).strip() or None


def _address_label(contact: Contact | None) -> str | None:
    """A one-line postal address for the contact card, blanks skipped."""
    if contact is None:
        return None
    street = " ".join(p for p in (contact.street, contact.number) if p).strip()
    city = " ".join(p for p in (contact.postal_code, contact.city) if p).strip()
    return ", ".join(p for p in (street, city) if p) or None


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


# --- master-data cards (ADR-0013 §4) ---------------------------------------


async def reindex_dienstleister_card(
    app_session: AsyncSession,
    rag_session: AsyncSession,
    embedder: Embedder,
    *,
    property_id: uuid.UUID,
    contact_id: uuid.UUID,
    force: bool = False,
) -> IndexResult | None:
    """Render one vendor's aggregate on one property to a German card and index
    it as master-data. Returns None if the property is gone or the vendor has no
    invoices there. Flushes the rag_session; the caller commits."""
    prop = await app_session.get(Property, property_id)
    if prop is None:
        return None
    vendors = await load_vendors_for_property(app_session, property_id=property_id)
    vendor = next((v for v in vendors if v.contact_id == contact_id), None)
    if vendor is None:
        return None
    # A nameless vendor card ("Dienstleister: ?") is pure noise in the assistant
    # — it can't be a meaningful citation. Skip it so it never pollutes
    # retrieval/citations.
    if not (vendor.name or "").strip() or vendor.name.strip() == "?":
        return None

    card = build_dienstleister_card(
        name=vendor.name,
        property_label=_property_label(prop),
        invoice_count=vendor.invoice_count,
        current_year=date.today().year,
        total_amount=vendor.total_amount,
        last_service_date=(
            vendor.last_service_date.isoformat() if vendor.last_service_date else None
        ),
        email=vendor.email,
        phone=vendor.phone,
        recent_services=[inv.name for inv in vendor.recent_invoices],
    )
    return await index_masterdata_card(
        rag_session,
        embedder,
        document_id=dienstleister_doc_id(property_id, contact_id),
        organization_id=prop.organization_id,
        source_type=SOURCE_TYPE_DIENSTLEISTER,
        card_text=card,
        contact_id=contact_id,
        contact_name=vendor.name,
        property_id=property_id,
        source_kind="DIENSTLEISTER",
        force=force,
    )


async def reindex_contact_card(
    app_session: AsyncSession,
    rag_session: AsyncSession,
    embedder: Embedder,
    *,
    property_id: uuid.UUID,
    contact_id: uuid.UUID,
    force: bool = False,
) -> IndexResult | None:
    """Render one owner/tenant contact on one property to a German card and
    index it as master-data (``sensitivity=high``). Returns None if the property
    or contact is gone, or the contact has no contract on that property. Flushes
    the rag_session; the caller commits."""
    prop = await app_session.get(Property, property_id)
    if prop is None:
        return None
    contact = await app_session.get(Contact, contact_id)
    if contact is None:
        return None
    name = _contact_label(contact)
    if not name:
        return None

    # The contact's contract on this property gives us the role + unit. If they
    # have none, they don't belong to this property → no card.
    row = (
        await app_session.execute(
            select(Contract.type, Contract.unit_id)
            .join(ContractContact, ContractContact.contract_id == Contract.id)
            .where(
                ContractContact.contact_id == contact_id,
                Contract.property_id == property_id,
            )
            .order_by(Contract.end_date.is_(None).desc(), Contract.end_date.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    ctype, unit_id = row
    unit_label = _unit_label(await app_session.get(Unit, unit_id)) if unit_id is not None else None

    card = build_contact_card(
        name=name,
        role=_CONTRACT_ROLE_LABEL.get(ctype),
        property_label=_property_label(prop),
        unit_label=unit_label,
        email=contact.email,
        phone=contact.phone,
        address=_address_label(contact),
    )
    return await index_masterdata_card(
        rag_session,
        embedder,
        document_id=contact_doc_id(property_id, contact_id),
        organization_id=prop.organization_id,
        source_type=SOURCE_TYPE_CONTACT,
        card_text=card,
        contact_id=contact_id,
        contact_name=name,
        property_id=property_id,
        sensitivity="high",
        source_kind="KONTAKT",
        force=force,
    )


async def reindex_etv_card(
    app_session: AsyncSession,
    rag_session: AsyncSession,
    embedder: Embedder,
    *,
    property_id: uuid.UUID,
    assembly_id: uuid.UUID,
    force: bool = False,
) -> IndexResult | None:
    """Render one Eigentümerversammlung (Termin, Ort, Status, Tagesordnung,
    Beschlüsse) to a German card and index it as master-data. Visible to every
    member of the property (see resolve_caller_scope). Returns None if the
    property or assembly is gone. Flushes the rag_session; the caller commits."""
    prop = await app_session.get(Property, property_id)
    if prop is None:
        return None
    assembly = await app_session.get(EtvAssembly, assembly_id)
    if assembly is None or assembly.deleted_at is not None or assembly.property_id != property_id:
        return None

    items = (
        await app_session.scalars(
            select(EtvAgendaItem)
            .where(EtvAgendaItem.assembly_id == assembly_id)
            .order_by(EtvAgendaItem.position)
        )
    ).all()
    agenda = [f"TOP {it.position}: {it.title}" for it in items]
    beschluesse: list[str] = []
    for it in items:
        if it.type != AgendaItemType.BESCHLUSS:
            continue
        result = _VOTE_RESULT_LABEL.get(it.vote_result) if it.vote_result is not None else None
        text = it.beschluss_text or it.title
        beschluesse.append(f"{text} — {result}" if result else text)

    card = build_etv_card(
        title=assembly.title,
        property_label=_property_label(prop),
        date=assembly.scheduled_start.strftime("%d.%m.%Y, %H:%M")
        if assembly.scheduled_start
        else None,
        location=assembly.location,
        status=_ASSEMBLY_STATUS_LABEL.get(assembly.status),
        agenda=agenda,
        beschluesse=beschluesse,
    )
    return await index_masterdata_card(
        rag_session,
        embedder,
        document_id=etv_doc_id(property_id, assembly_id),
        organization_id=prop.organization_id,
        source_type=SOURCE_TYPE_ETV,
        card_text=card,
        property_id=property_id,
        source_kind="ETV",
        force=force,
    )


async def reindex_anfrage_card(
    app_session: AsyncSession,
    rag_session: AsyncSession,
    embedder: Embedder,
    *,
    organization_id: uuid.UUID,
    inquiry_id: uuid.UUID,
    force: bool = False,
) -> IndexResult | None:
    """Render one anfragen@ offer inquiry to a German card and index it as
    VERWALTER-only master-data (prospect PII, ``sensitivity=high`` — kept
    Verwalter-only by the synthetic ``anfrage:`` document id, like Dienstleister).
    When the inquiry is gone, out of org, or IGNORED, the card is PURGED from
    the store instead and None is returned — deleting an inquiry (DSGVO
    erasure) must take its PII card with it. Flushes the rag_session; the
    caller commits (also on the None/purge path)."""
    inquiry = await app_session.get(OfferInquiry, inquiry_id)
    if (
        inquiry is None
        or inquiry.organization_id != organization_id
        or inquiry.status == OfferInquiryStatus.IGNORED.value
    ):
        await delete_masterdata_card(
            rag_session, document_id=anfrage_doc_id(organization_id, inquiry_id)
        )
        return None
    # Besichtigungen from the Fahrtenbuch (trips linked to this inquiry).
    visit_row = (
        await app_session.execute(
            select(
                func.max(func.coalesce(Trip.ended_at, Trip.started_at)), func.count(Trip.id)
            ).where(Trip.inquiry_id == inquiry.id)
        )
    ).one()
    visited_at, visit_count = visit_row[0], int(visit_row[1] or 0)
    card = build_anfrage_card(
        sender_name=inquiry.sender_name,
        sender_email=inquiry.sender_email,
        subject=inquiry.subject or None,
        art=inquiry.art,
        object_address=inquiry.object_address,
        units=inquiry.units,
        status=inquiry.status,
        lead_status=inquiry.lead_status,
        received_on=inquiry.created_at.date().isoformat() if inquiry.created_at else None,
        visited_on=visited_at.date().isoformat() if visited_at else None,
        visit_count=visit_count or None,
    )
    return await index_masterdata_card(
        rag_session,
        embedder,
        document_id=anfrage_doc_id(organization_id, inquiry_id),
        organization_id=organization_id,
        source_type=SOURCE_TYPE_ANFRAGE,
        card_text=card,
        contact_name=inquiry.sender_name or inquiry.sender_email,
        sensitivity="high",
        source_kind="ANFRAGE",
        force=force,
    )


async def _contact_ids_for_property(
    app_session: AsyncSession, property_id: uuid.UUID
) -> list[uuid.UUID]:
    """Distinct contacts that have a contract on the property (owners/tenants)."""
    return list(
        (
            await app_session.scalars(
                select(Contact.id)
                .join(ContractContact, ContractContact.contact_id == Contact.id)
                .join(Contract, Contract.id == ContractContact.contract_id)
                .where(Contract.property_id == property_id)
                .distinct()
            )
        ).all()
    )


async def _assembly_ids_for_property(
    app_session: AsyncSession, property_id: uuid.UUID
) -> list[uuid.UUID]:
    """Non-deleted ETV assemblies on the property."""
    return list(
        (
            await app_session.scalars(
                select(EtvAssembly.id).where(
                    EtvAssembly.property_id == property_id,
                    EtvAssembly.deleted_at.is_(None),
                )
            )
        ).all()
    )


async def enqueue_masterdata_indexing(
    app_session: AsyncSession,
    *,
    settings: Settings,
    property_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> int:
    """Enqueue ``index_rag_masterdata`` for every master-data card on each
    property: one Dienstleister card per vendor, one contact card per
    owner/tenant, and one ETV card per Eigentümerversammlung. No-op returning 0
    when rag is off. Unlike documents there's no "only_new" gate: cards are
    cheap to re-render and the content-hash skip in ``index_masterdata_card``
    makes re-runs idempotent."""
    if not settings.rag_enabled:
        return 0

    prop_stmt = select(Property.id)
    if property_id is not None:
        prop_stmt = prop_stmt.where(Property.id == property_id)
    property_ids = list((await app_session.scalars(prop_stmt)).all())

    # (property_id, entity_id, card_type) — card_type routes the worker to the
    # right reindex fn (Dienstleister / contact / ETV).
    pairs: list[tuple[uuid.UUID, uuid.UUID, str]] = []
    for pid in property_ids:
        vendors = await load_vendors_for_property(app_session, property_id=pid)
        pairs.extend((pid, vendor.contact_id, SOURCE_TYPE_DIENSTLEISTER) for vendor in vendors)
        contact_ids = await _contact_ids_for_property(app_session, pid)
        pairs.extend((pid, cid, SOURCE_TYPE_CONTACT) for cid in contact_ids)
        assembly_ids = await _assembly_ids_for_property(app_session, pid)
        pairs.extend((pid, aid, SOURCE_TYPE_ETV) for aid in assembly_ids)

    # Anfragen (offer inquiries) are org-scoped, not per-property — only sweep
    # them on a full backfill. The first tuple slot carries the organization id
    # for these rows (the worker routes "anfrage" to reindex_anfrage_card).
    if property_id is None:
        anfrage_rows = (
            await app_session.execute(
                select(OfferInquiry.organization_id, OfferInquiry.id).where(
                    OfferInquiry.status != OfferInquiryStatus.IGNORED.value
                )
            )
        ).all()
        pairs.extend((org_id, inq_id, SOURCE_TYPE_ANFRAGE) for org_id, inq_id in anfrage_rows)

    if limit is not None:
        pairs = pairs[:limit]

    # Lazy import avoids an import cycle (tasks imports this module).
    from app.workers.tasks import index_rag_masterdata

    for pid, cid, card_type in pairs:
        index_rag_masterdata.delay(str(pid), str(cid), card_type)
    return len(pairs)


async def index_law_corpus(
    rag_session: AsyncSession,
    embedder: Embedder,
    *,
    organization_id: uuid.UUID,
    force: bool = False,
) -> tuple[int, int]:
    """Index the committed Gesetzes-Korpus (WEG, HeizkostenV, BGB-Auszug —
    one card per Paragraph, ~100 total) for one org. Public by design:
    retrieval admits ``source_type=law`` for every caller. Content-hash
    makes re-runs cheap; snapshots live in ``app/rag/assets/law/``
    (amtliche Werke, § 5 UrhG). Returns (indexed, skipped). Flushes; the
    caller commits."""
    import json
    from pathlib import Path

    from app.rag.masterdata import SOURCE_TYPE_LAW, build_law_card, law_doc_id

    assets = Path(__file__).parent / "assets" / "law"
    indexed = skipped = 0
    current_ids: set[uuid.UUID] = set()
    for asset in sorted(assets.glob("*.json")):
        for entry in json.loads(asset.read_text(encoding="utf-8")):
            card = build_law_card(
                law=entry["law"],
                law_name=entry["law_name"],
                paragraph=entry["paragraph"],
                title=entry["title"],
                text=entry["text"],
            )
            result = await index_masterdata_card(
                rag_session,
                embedder,
                document_id=law_doc_id(organization_id, entry["law"], entry["paragraph"]),
                organization_id=organization_id,
                source_type=SOURCE_TYPE_LAW,
                card_text=card,
                source_kind="GESETZ",
                force=force,
            )
            if result.skipped:
                skipped += 1
            else:
                indexed += 1
            current_ids.add(law_doc_id(organization_id, entry["law"], entry["paragraph"]))
    # Sweep: a repealed/renumbered § must not linger as authoritative law.
    # Chunks carry source_type, documents only source_kind ("GESETZ").
    from sqlalchemy import delete as sa_delete

    from app.rag.models import RagChunk

    await rag_session.execute(
        sa_delete(RagChunk).where(
            RagChunk.organization_id == organization_id,
            RagChunk.source_type == SOURCE_TYPE_LAW,
            RagChunk.document_id.notin_(current_ids),
        )
    )
    await rag_session.execute(
        sa_delete(RagDocument).where(
            RagDocument.organization_id == organization_id,
            RagDocument.source_kind == "GESETZ",
            RagDocument.document_id.notin_(current_ids),
        )
    )
    await rag_session.flush()
    return indexed, skipped
