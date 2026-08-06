"""Service helpers for the property-vendor view.

Builds VendorSummary rows from `documents` where `kind = RECHNUNG`
+ `property_id = …`. One vendor = one `contact_id`; aggregates
invoice count + a CURRENT-YEAR cost total + first/last service dates +
the full invoice list in two queries.
"""

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import cast

from sqlalchemy import ColumnElement, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Contact, Document
from app.models.contact import ContactKind
from app.models.document import DocumentKind
from app.schemas.vendor import VendorInvoiceSummary, VendorSummary
from app.services.units import _contact_label


def not_reversed_filter(reversed_invoice_ids: set[int]) -> ColumnElement[bool]:
    """Exclude documents whose Impower invoice was storniert.

    `sourceId` on the mirrored `raw_jsonb` IS the Impower invoice id (the
    same join the invoice-detail endpoint makes). The explicit NULL arm
    matters: `NULL NOT IN (...)` evaluates to NULL, so without it every
    invoice document lacking a sourceId would silently vanish from the
    vendor view.
    """
    source_id = Document.raw_jsonb["sourceId"].astext
    return or_(
        source_id.is_(None),
        source_id.notin_([str(i) for i in reversed_invoice_ids]),
    )


async def load_vendors_for_property(
    session: AsyncSession,
    *,
    property_id: uuid.UUID,
    recent_limit: int | None = None,
    reversed_invoice_ids: set[int] | None = None,
) -> list[VendorSummary]:
    """Aggregate invoice docs by vendor contact + return one row per
    vendor, ordered by most-recent service first.

    `total_amount` is the CURRENT calendar year's cost only (a
    conditional sum) — owners care about "what did this vendor cost us
    this year", not the all-time figure. `invoice_count` and the
    returned invoice list stay all-time so the full history is visible
    (the clients group them by year).

    Two round-trips:
      1. Aggregate query (count, current-year sum, min/max issued_date)
         joined to contacts so we can render the label + contact bits in
         the same pass.
      2. Invoice fetch keyed on the vendor ids we just found. By default
         ALL invoices come back (clients group by year); pass
         `recent_limit` to truncate to the N most recent per vendor.
         With typical Verwalter inventories (≤ ~30 vendors per property,
         ≤ ~200 invoices total) this is cheap.

    Vendors with NULL contact_id on every invoice are skipped — they
    show up as "unbekannt" on the admin side, but owners shouldn't
    see them in a "who do I call?" list because there's nothing to
    call.

    `reversed_invoice_ids` drops storno bookings from the owner-facing
    view. It is applied to BOTH queries on purpose: filtering only the
    invoice list would leave invoice_count, the year total and the
    first/last service dates counting invoices the caller cannot see.
    Verwalter pass None and keep the full bookkeeping picture.
    """
    # Current-year window for the cost total. Invoices outside it still
    # count toward invoice_count + the list, but not the € total.
    year_start = date(date.today().year, 1, 1)
    next_year_start = date(date.today().year + 1, 1, 1)
    current_year_amount = case(
        (
            and_(
                Document.issued_date >= year_start,
                Document.issued_date < next_year_start,
            ),
            Document.amount,
        ),
        else_=0,
    )

    storno_filters: list[ColumnElement[bool]] = []
    if reversed_invoice_ids:
        storno_filters.append(not_reversed_filter(reversed_invoice_ids))

    # ----- 1. Per-vendor aggregate -----
    agg_q = (
        select(
            Contact.id.label("contact_id"),
            Contact.kind,
            Contact.email,
            Contact.phone,
            # Pulled so `_contact_label` can compute the rendered
            # label without an extra fetch.
            Contact.salutation,
            Contact.title,
            Contact.first_name,
            Contact.last_name,
            Contact.company_name,
            Contact.recipient_name,
            func.count(Document.id).label("invoice_count"),
            func.sum(current_year_amount).label("total_amount"),
            func.min(Document.issued_date).label("first_service_date"),
            func.max(Document.issued_date).label("last_service_date"),
        )
        .join(Document, Document.contact_id == Contact.id)
        .where(
            Document.property_id == property_id,
            Document.kind == DocumentKind.RECHNUNG,
            Document.deleted_at.is_(None),
            Contact.deleted_at.is_(None),
            *storno_filters,
        )
        .group_by(Contact.id)
        .order_by(func.max(Document.issued_date).desc().nulls_last())
    )
    rows = (await session.execute(agg_q)).all()
    if not rows:
        return []

    vendor_ids = [r.contact_id for r in rows]

    # ----- 2. Invoices per vendor -----
    # One flat fetch ordered by date; bucket into per-vendor lists in
    # Python. By default keep ALL of them (the clients group by year);
    # only trim when the caller passes `recent_limit`.
    inv_q = (
        select(
            Document.id,
            Document.name,
            Document.issued_date,
            Document.amount,
            Document.contact_id,
        )
        .where(
            Document.property_id == property_id,
            Document.kind == DocumentKind.RECHNUNG,
            Document.deleted_at.is_(None),
            Document.contact_id.in_(vendor_ids),
            *storno_filters,
        )
        .order_by(Document.issued_date.desc().nulls_last(), Document.created_at.desc())
    )
    recent_by_vendor: dict[uuid.UUID, list[VendorInvoiceSummary]] = defaultdict(list)
    for r in (await session.execute(inv_q)).all():
        bucket = recent_by_vendor[r.contact_id]
        if recent_limit is not None and len(bucket) >= recent_limit:
            continue
        bucket.append(
            VendorInvoiceSummary(
                id=r.id,
                name=r.name,
                issued_date=r.issued_date,
                amount=r.amount,
            )
        )

    # ----- 3. Compose -----
    out: list[VendorSummary] = []
    for r in rows:
        # Reuse the rendered-label helper used by unit contract chips
        # — keeps the "Dr. Max Mustermann" / "Acme GmbH" rule in one
        # place. _contact_label takes a Contact row, but we already
        # have the fields it needs, so build a lightweight shim.
        contact_shim = _ContactRowShim(
            kind=r.kind,
            salutation=r.salutation,
            title=r.title,
            first_name=r.first_name,
            last_name=r.last_name,
            company_name=r.company_name,
            recipient_name=r.recipient_name,
        )
        out.append(
            VendorSummary(
                contact_id=r.contact_id,
                # `_contact_label` reads attributes via duck-typing
                # — the shim provides exactly those, but mypy can't
                # prove the structural-compat without a Protocol.
                # Cast keeps the helper's signature unchanged.
                name=_contact_label(cast(Contact, contact_shim)),
                kind=r.kind,
                email=r.email,
                phone=r.phone,
                invoice_count=int(r.invoice_count or 0),
                total_amount=Decimal(r.total_amount) if r.total_amount is not None else None,
                first_service_date=r.first_service_date,
                last_service_date=r.last_service_date,
                recent_invoices=recent_by_vendor.get(r.contact_id, []),
            )
        )
    return out


class _ContactRowShim:
    """Duck-typed shim matching the subset of Contact attributes
    `_contact_label` reads. Lets the aggregate query stay flat
    instead of dragging the full Contact ORM object through."""

    __slots__ = (
        "company_name",
        "first_name",
        "kind",
        "last_name",
        "recipient_name",
        "salutation",
        "title",
    )

    def __init__(
        self,
        *,
        kind: ContactKind,
        salutation: str | None,
        title: str | None,
        first_name: str | None,
        last_name: str | None,
        company_name: str | None,
        recipient_name: str | None,
    ) -> None:
        self.kind = kind
        self.salutation = salutation
        self.title = title
        self.first_name = first_name
        self.last_name = last_name
        self.company_name = company_name
        self.recipient_name = recipient_name


# Re-export so wildcard imports from `app.services.vendors` work the
# same as `from app.services.vendors import load_vendors_for_property`.
__all__ = ["load_vendors_for_property", "not_reversed_filter"]
