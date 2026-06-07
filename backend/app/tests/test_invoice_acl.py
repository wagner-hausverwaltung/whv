"""Owner access to WEG vendor invoices (Dienstleister section).

A vendor invoice is ``kind=RECHNUNG`` pinned to the VENDOR's ``contact_id``
(the vendors service buckets by it) with no unit/contract FK — a WEG-wide
expense every owner is entitled to. The generic ``_document_visibility_filter``
only matched a doc's ``contact_id`` against the CALLER's own contact, so it hid
vendor invoices from owners: the list showed them but the detail + PDF download
404'd ("Invoice not found" / "Download failed"). ``_invoice_visibility_filter``
additionally admits any RECHNUNG with no unit/contract pin, while a
unit/contract-pinned invoice stays scoped.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.api.v1.me import _document_visibility_filter, _invoice_visibility_filter
from app.models import Contact, ContactKind, Document, DocumentKind, UserRole
from app.tests._factories import (
    make_contact_with_contract_link,
    make_document,
    make_org,
    make_property,
    make_unit,
    make_user,
)


async def test_owner_sees_weg_vendor_invoice_but_not_scoped_one(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    # Owner: Contact (impower_id 5001) + active OWNER contract on their unit.
    owner_unit = await make_unit(test_engine, org=org, prop=prop)
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=5001, unit=owner_unit
    )
    owner, _, _ = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=5001
    )

    # Vendor contact (no contract of its own).
    async with sm() as s:
        vendor = Contact(
            organization_id=org.id, kind=ContactKind.COMPANY, company_name="Acme GmbH"
        )
        s.add(vendor)
        await s.commit()
        await s.refresh(vendor)

    # WEG vendor invoice: RECHNUNG pinned to the vendor, no unit/contract.
    weg_invoice = await make_document(
        test_engine, org=org, prop=prop, kind=DocumentKind.RECHNUNG, contact=vendor
    )
    # A RECHNUNG pinned to ANOTHER unit the owner isn't on → must stay hidden.
    other_unit = await make_unit(test_engine, org=org, prop=prop)
    scoped_invoice = await make_document(
        test_engine,
        org=org,
        prop=prop,
        kind=DocumentKind.RECHNUNG,
        unit=other_unit,
        contact=vendor,
    )

    async def _visible(filter_expr: object) -> set[object]:
        async with sm() as s:
            return set(
                (
                    await s.scalars(
                        select(Document.id).where(
                            Document.property_id == prop.id, filter_expr
                        )
                    )
                ).all()
            )

    # The OLD generic filter hid the WEG vendor invoice — that was the bug.
    assert weg_invoice.id not in await _visible(_document_visibility_filter(owner))

    # The invoice-aware filter admits the WEG vendor invoice…
    new_visible = await _visible(_invoice_visibility_filter(owner))
    assert weg_invoice.id in new_visible
    # …but a unit-pinned invoice on a unit the owner isn't on stays hidden.
    assert scoped_invoice.id not in new_visible
