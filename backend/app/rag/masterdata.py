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
