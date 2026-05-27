"""Schemas for the per-invoice detail dialog under the Dienstleister
tab.

`GET /me/properties/{id}/invoices/{source_id}` looks up the row in
our local `documents` mirror (to verify property scope and pull the
right Impower invoice id), then fetches the structured invoice from
Impower on demand. The line items carry the bookkeeping detail
owners actually want to see — what was the money spent on
("Primärenergie" / "Sonstige Reparaturen" / "Stromlieferung
15.04.2025-31.12.2025"), in which account category, with which VAT.

We don't mirror the invoice itself locally — too high churn rate
and the data is read-once-per-click for owners. If usage spikes
we can cache in §1.4d iter 2.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class InvoiceLineItemResponse(BaseModel):
    """One posting row from an Impower invoice.

    `account_name` is the human label ("Reparaturen Heizung",
    "Primärenergie", "Passive Rechnungsabgrenzungsposten"); the
    `account_code` is the SKR03-style number ("49"). Owners care
    about the name + booking text. Verwalter cares about both.
    """

    account_code: str | None = None
    account_name: str | None = None
    booking_text: str | None = None
    amount: Decimal | None = None
    vat_amount: Decimal | None = None
    vat_percentage: Decimal | None = None


class InvoiceDetailResponse(BaseModel):
    """Header + items for the invoice-detail dialog."""

    # Impower's own invoice number ("000016141105") — distinct from
    # the document name on our side ("R26/01384 …"). Surfaced
    # because owners reconcile against bank statements that quote
    # this.
    invoice_number: str | None = None
    issued_date: date | None = None
    amount: Decimal | None = None
    state: str | None = None
    # Render-ready vendor label. The contact is already on the
    # parent VendorSummary so this is a sanity-check field —
    # double-rendering harmless.
    counterpart_name: str | None = None
    # Order-required IBAN + BIC for owners who want to verify the
    # bank account a SEPA mandate is hitting.
    counterpart_iban: str | None = None
    counterpart_bic: str | None = None
    items: list[InvoiceLineItemResponse] = []
