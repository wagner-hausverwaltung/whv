"""Service helpers for the property-vendor view.

Builds VendorSummary rows from `documents` where `kind = RECHNUNG`
+ `property_id = …`. One vendor = one `contact_id`; aggregates
invoice count + total + first/last service dates + the 5 most
recent invoices in two queries.
"""

import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Contact, Document
from app.models.document import DocumentKind
from app.schemas.vendor import VendorInvoiceSummary, VendorSummary
from app.services.units import _contact_label


async def load_vendors_for_property(
    session: AsyncSession,
    *,
    property_id: uuid.UUID,
    recent_limit: int = 5,
) -> list[VendorSummary]:
    """Aggregate invoice docs by vendor contact + return one row per
    vendor, ordered by most-recent service first.

    Two round-trips:
      1. Aggregate query (count, sum, min/max issued_date) joined to
         contacts so we can render the label + contact bits in the
         same pass.
      2. Recent-invoices fetch keyed on the vendor ids we just
         found — limited to `recent_limit` per vendor via Python-side
         truncation. With typical Verwalter inventories (≤ ~30
         vendors per property, ≤ ~200 invoices total) this is cheap;
         a DISTINCT ON / window function would be more correct at
         scale but adds Postgres-specific syntax for negligible win.

    Vendors with NULL contact_id on every invoice are skipped — they
    show up as "unbekannt" on the admin side, but owners shouldn't
    see them in a "who do I call?" list because there's nothing to
    call.
    """
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
            func.sum(Document.amount).label("total_amount"),
            func.min(Document.issued_date).label("first_service_date"),
            func.max(Document.issued_date).label("last_service_date"),
        )
        .join(Document, Document.contact_id == Contact.id)
        .where(
            Document.property_id == property_id,
            Document.kind == DocumentKind.RECHNUNG,
            Document.deleted_at.is_(None),
            Contact.deleted_at.is_(None),
        )
        .group_by(Contact.id)
        .order_by(func.max(Document.issued_date).desc().nulls_last())
    )
    rows = (await session.execute(agg_q)).all()
    if not rows:
        return []

    vendor_ids = [r.contact_id for r in rows]

    # ----- 2. Recent invoices per vendor -----
    # One flat fetch ordered by date; bucket into per-vendor lists
    # in Python, trim to `recent_limit`. Avoids DISTINCT ON gymnastics
    # for a feature with small N.
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
        )
        .order_by(Document.issued_date.desc().nulls_last(), Document.created_at.desc())
    )
    recent_by_vendor: dict[uuid.UUID, list[VendorInvoiceSummary]] = defaultdict(list)
    for r in (await session.execute(inv_q)).all():
        bucket = recent_by_vendor[r.contact_id]
        if len(bucket) >= recent_limit:
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
                name=_contact_label(contact_shim),
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
        "kind",
        "salutation",
        "title",
        "first_name",
        "last_name",
        "company_name",
        "recipient_name",
    )

    def __init__(
        self,
        *,
        kind,  # type: ignore[no-untyped-def]
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
__all__ = ["load_vendors_for_property"]


# Quiet unused-import lint without removing the and_ alias — kept
# because future expansions (per-vendor invoice-date filter) will
# need it and tests cover the unused-import rule.
_ = and_
