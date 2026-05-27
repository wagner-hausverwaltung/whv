"""Schemas for the property-vendor view.

`GET /me/properties/{id}/vendors` returns a per-vendor aggregate
keyed by `contact_id`. The portal renders each as a card with
name + phone + email + recent invoices, so owners can call back the
firm that handled a past issue.

Privacy posture (see PR discussion / ADR-0010): owners get the
contactable bits only — no postal address, no mandate / VAT / bank
fields. Verwalter has the admin SPA for the full record.
"""

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.contact import ContactKind


class VendorInvoiceSummary(BaseModel):
    """One invoice row for the vendor card's recent-history list.

    Doesn't carry the storage URL — the portal links into the
    existing `/me/properties/{id}/documents/{doc_id}` flow for the
    actual file. We just need enough context to render the row.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    issued_date: date | None = None
    amount: Decimal | None = None


class VendorSummary(BaseModel):
    """One vendor card. Aggregates all RECHNUNG documents on the
    property whose `contact_id` matches this contact."""

    model_config = ConfigDict(from_attributes=True)

    contact_id: uuid.UUID
    # Server-rendered label so clients don't reimplement
    # PERSON vs COMPANY name logic (matches contract chips elsewhere).
    name: str
    kind: ContactKind
    # The actionable bits. Phone + email are both optional — Impower
    # data hygiene means some contacts have only one or neither.
    email: str | None = None
    phone: str | None = None
    # Aggregate stats — drives the "last service" date on the card
    # header and the running total in the expanded body.
    invoice_count: int
    total_amount: Decimal | None = None
    first_service_date: date | None = None
    last_service_date: date | None = None
    # Most-recent 5 invoices — enough for the expandable card body
    # without forcing the SPA to fetch a paginated list.
    recent_invoices: list[VendorInvoiceSummary] = []
