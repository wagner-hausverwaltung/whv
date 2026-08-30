"""Master-data "cards" for the RAG store (ADR-0013 §4).

Dienstleister / Kontakte aren't documents — instead of risky text-to-SQL we
render each to a compact German text card ("Dienstleister: Mustermann GmbH ·
Objekt: … · 2025 Summe: 4.812,00 €"), embed it, and store it as a chunk with
the same §2 ACL scope columns documents use.

The clever bit: a card carries a SYNTHETIC ``document_id`` (a deterministic
UUIDv5 of the entity), so it slots into the existing ``rag_chunks`` schema +
retrieval path with **no migration**. ACL falls out for free: a non-VERWALTER's
retrieval is gated to their real visible ``document_id`` set, which a synthetic
id can never be a member of — so Dienstleister cards are **VERWALTER-only by
construction** (the §4 sensitivity rule), without touching the ACL filter.
VERWALTER has no document-id gate, so they retrieve them. Contacts (PII,
``sensitivity=high``) come in a later increment under stricter rules.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.rag.metadata import format_eur

# Fixed namespace so the same (property, vendor) always maps to the same
# synthetic document id — keeps re-indexing idempotent and lets us replace a
# card's prior rows by that id (mirrors how documents key off Document.id).
_MASTERDATA_NS = uuid.UUID("5d3a9f00-2c41-4e8e-9a7b-6f0c1d2e3f40")

# Tags stored in rag_chunks.source_type for these rows (vs. "document").
SOURCE_TYPE_DIENSTLEISTER = "dienstleister"
SOURCE_TYPE_CONTACT = "contact"
SOURCE_TYPE_ETV = "etv"
SOURCE_TYPE_ANFRAGE = "anfrage"
SOURCE_TYPE_LAW = "law"


def dienstleister_doc_id(property_id: uuid.UUID, contact_id: uuid.UUID) -> uuid.UUID:
    """Deterministic synthetic document id for one vendor card on one property."""
    return uuid.uuid5(_MASTERDATA_NS, f"dienstleister:{property_id}:{contact_id}")


def contact_doc_id(property_id: uuid.UUID, contact_id: uuid.UUID) -> uuid.UUID:
    """Deterministic synthetic document id for one contact card on one property.

    The ``contact:`` prefix keeps it disjoint from ``dienstleister_doc_id`` so a
    vendor card and a contact card for the same (property, contact) never
    collide — and so the data-subject admission in ``resolve_caller_scope`` only
    ever matches contact cards, never Dienstleister cards (which stay
    VERWALTER-only).
    """
    return uuid.uuid5(_MASTERDATA_NS, f"contact:{property_id}:{contact_id}")


def etv_doc_id(property_id: uuid.UUID, assembly_id: uuid.UUID) -> uuid.UUID:
    """Deterministic synthetic document id for one ETV (Eigentümerversammlung)
    card on one property. The ``etv:`` prefix keeps it disjoint from the other
    card kinds. ETV cards are visible to every member of the property (see
    ``resolve_caller_scope``), matching the portal's ETV tab and the
    property-wide invitation/protocol documents."""
    return uuid.uuid5(_MASTERDATA_NS, f"etv:{property_id}:{assembly_id}")


def anfrage_doc_id(organization_id: uuid.UUID, inquiry_id: uuid.UUID) -> uuid.UUID:
    """Deterministic synthetic document id for one anfragen@ offer inquiry.

    Anfragen are org-scoped (prospect-initiated, not tied to a property), so the
    id keys off (organization, inquiry). The ``anfrage:`` prefix keeps it
    disjoint from the other card kinds — and since a non-VERWALTER's retrieval
    scope is built only from real docs + their own contact + ETV cards, an
    ``anfrage`` synthetic id is never in that set → **VERWALTER-only by
    construction** (prospect PII, ``sensitivity=high``), like Dienstleister.
    """
    return uuid.uuid5(_MASTERDATA_NS, f"anfrage:{organization_id}:{inquiry_id}")


def build_anfrage_card(
    *,
    sender_name: str | None,
    sender_email: str,
    subject: str | None = None,
    art: str | None = None,
    object_address: str | None = None,
    units: int | None = None,
    status: str | None = None,
    lead_status: str | None = None,
    received_on: str | None = None,
    visited_on: str | None = None,
    visit_count: int | None = None,
) -> str:
    """Render one inbound offer inquiry (Anfrage) to a compact German card so the
    assistant can answer "wie lautet die Kontakt-Mail der Anfrage zur WEG in …?",
    "welche offenen Anfragen gibt es?" or "wurde die Anfrage … schon besichtigt?"
    (``visited_on`` comes from the Fahrtenbuch). VERWALTER-only (prospect PII)."""
    who = sender_name or sender_email
    parts: list[str] = [f"Anfrage (anfragen@): {who}"]
    if sender_name and sender_email:
        parts.append(f"E-Mail: {sender_email}")
    if subject:
        parts.append(f"Betreff: {subject}")
    if art:
        parts.append(f"Art: {art}")
    if object_address:
        parts.append(f"Objekt: {object_address}")
    if units is not None:
        parts.append(f"Einheiten: {units}")
    if status:
        parts.append(f"Bearbeitung: {status}")
    if lead_status:
        parts.append(f"Status: {lead_status}")
    if received_on:
        parts.append(f"Eingegangen: {received_on}")
    if visited_on:
        times = f" ({visit_count}x)" if visit_count and visit_count > 1 else ""
        parts.append(f"Besichtigt: {visited_on}{times}")
    return " · ".join(parts)


def build_dienstleister_card(
    *,
    name: str,
    property_label: str | None = None,
    invoice_count: int | None = None,
    current_year: int | None = None,
    total_amount: Decimal | None = None,
    last_service_date: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    recent_services: list[str] | None = None,
) -> str:
    """Render a vendor's aggregate to a compact, embeddable German card.

    Skips absent fields (Impower data hygiene leaves many blank), mirroring
    ``build_metadata_header``. Money is German-formatted via ``format_eur``.
    """
    parts: list[str] = [f"Dienstleister: {name}"]
    if property_label:
        parts.append(f"Objekt: {property_label}")
    if invoice_count is not None:
        parts.append(f"Rechnungen gesamt: {invoice_count}")
    if total_amount is not None:
        year = f"{current_year} " if current_year is not None else ""
        parts.append(f"{year}Summe: {format_eur(total_amount)}")
    if last_service_date:
        parts.append(f"letzte Leistung: {last_service_date}")
    contact_bits = ", ".join(b for b in (email, phone) if b)
    if contact_bits:
        parts.append(f"Kontakt: {contact_bits}")
    if recent_services:
        # Cap the leistungen list so the card stays a *card* (one embed-worth
        # of signal), not a dump of every invoice title.
        shown = [s for s in recent_services if s][:8]
        if shown:
            parts.append("Leistungen: " + "; ".join(shown))
    return " · ".join(parts)


def build_contact_card(
    *,
    name: str,
    role: str | None = None,
    property_label: str | None = None,
    unit_label: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    address: str | None = None,
) -> str:
    """Render an owner/tenant/Beirat contact to a compact German card.

    This is PII (``sensitivity=high``): kept VERWALTER-only by the synthetic
    document id, plus the data subject themselves via ``resolve_caller_scope``.
    Skips absent fields, like ``build_dienstleister_card``.
    """
    parts: list[str] = [f"Kontakt: {name}"]
    if role:
        parts.append(f"Rolle: {role}")
    if property_label:
        parts.append(f"Objekt: {property_label}")
    if unit_label:
        parts.append(f"Einheit: {unit_label}")
    reach = ", ".join(b for b in (email, phone) if b)
    if reach:
        parts.append(f"Erreichbar: {reach}")
    if address:
        parts.append(f"Anschrift: {address}")
    return " · ".join(parts)


def build_etv_card(
    *,
    title: str,
    property_label: str | None = None,
    date: str | None = None,
    location: str | None = None,
    status: str | None = None,
    agenda: list[str] | None = None,
    beschluesse: list[str] | None = None,
) -> str:
    """Render one Eigentümerversammlung to a compact German card.

    Carries the structured metadata the invitation/protocol PDFs bury in OCR
    text — Termin, Ort, Status, Tagesordnung and Beschlüsse — so the assistant
    can answer "wann war die letzte ETV / was wurde beschlossen?". The PDFs
    themselves are separate (citable, downloadable) document chunks. Skips
    absent fields like the other card builders.
    """
    # "(ETV)" so the common abbreviation matches the card in plain retrieval too.
    parts: list[str] = [f"Eigentümerversammlung (ETV): {title}"]
    if property_label:
        parts.append(f"Liegenschaft: {property_label}")
    if date:
        parts.append(f"Termin: {date}")
    if location:
        parts.append(f"Ort: {location}")
    if status:
        parts.append(f"Status: {status}")
    if agenda:
        shown = [a for a in agenda if a][:12]
        if shown:
            parts.append("Tagesordnung: " + "; ".join(shown))
    if beschluesse:
        shown = [b for b in beschluesse if b][:12]
        if shown:
            parts.append("Beschlüsse: " + "; ".join(shown))
    return " · ".join(parts)


def law_doc_id(organization_id: uuid.UUID, law: str, paragraph: str) -> uuid.UUID:
    """Deterministic synthetic document id for one Gesetzes-Paragraph.

    Law cards are indexed per org (single-org today; a future org re-runs the
    backfill). Unlike every other card kind they are PUBLIC: retrieval admits
    ``source_type=law`` chunks for every caller — Gesetzestexte sind amtliche
    Werke (§ 5 UrhG), there is nothing to protect."""
    return uuid.uuid5(_MASTERDATA_NS, f"law:{organization_id}:{law}:{paragraph}")


def build_law_card(*, law: str, law_name: str, paragraph: str, title: str, text: str) -> str:
    """Render one Paragraph as a retrieval card: '§ 21 WEG — Titel' + text."""
    head = f"{paragraph} {law}"
    if title:
        head += f" — {title}"
    return f"{head} ({law_name})\n\n{text}"
