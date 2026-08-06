"""Dienstleister aggregation: the per-vendor € total is the CURRENT
calendar year only, while invoice_count and the returned list stay
all-time (no 5-row cap)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.models import Contact, ContactKind, Document, DocumentKind
from app.services.vendors import load_vendors_for_property
from app.tests._factories import make_org, make_property


async def _add_invoice(
    sm: async_sessionmaker[Any],
    *,
    org_id: uuid.UUID,
    property_id: uuid.UUID,
    contact_id: uuid.UUID,
    issued: date,
    amount: str,
    name: str,
    source_id: int | None = None,
) -> None:
    async with sm() as s:
        s.add(
            Document(
                organization_id=org_id,
                property_id=property_id,
                contact_id=contact_id,
                kind=DocumentKind.RECHNUNG,
                name=name,
                issued_date=issued,
                amount=Decimal(amount),
                # Mirrors what the Impower sync writes; `sourceId` is the
                # invoice id the storno filter joins on.
                raw_jsonb={"sourceId": source_id} if source_id is not None else None,
            )
        )
        await s.commit()


async def test_vendor_total_is_current_year_only_and_lists_all(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    async with sm() as s:
        vendor = Contact(
            organization_id=org.id,
            kind=ContactKind.COMPANY,
            company_name="Acme GmbH",
        )
        s.add(vendor)
        await s.commit()
        await s.refresh(vendor)
        cid = vendor.id

    this_year = date.today().year
    # 2 current-year invoices (sum 150) + 4 prior-year (sum 999). Six
    # total proves the old 5-row cap is gone.
    await _add_invoice(
        sm,
        org_id=org.id,
        property_id=prop.id,
        contact_id=cid,
        issued=date(this_year, 3, 1),
        amount="100.00",
        name="cur-1",
    )
    await _add_invoice(
        sm,
        org_id=org.id,
        property_id=prop.id,
        contact_id=cid,
        issued=date(this_year, 6, 1),
        amount="50.00",
        name="cur-2",
    )
    for i, amt in enumerate(("400.00", "300.00", "200.00", "99.00")):
        await _add_invoice(
            sm,
            org_id=org.id,
            property_id=prop.id,
            contact_id=cid,
            issued=date(this_year - 1, 1 + i, 1),
            amount=amt,
            name=f"prior-{i}",
        )

    async with sm() as s:
        vendors = await load_vendors_for_property(s, property_id=prop.id)

    assert len(vendors) == 1
    v = vendors[0]
    assert v.name == "Acme GmbH"
    assert v.invoice_count == 6  # all-time count
    assert v.total_amount == Decimal("150.00")  # current year only
    assert len(v.recent_invoices) == 6  # no 5-row cap anymore


async def test_vendor_total_zero_when_no_current_year_invoices(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    async with sm() as s:
        vendor = Contact(
            organization_id=org.id,
            kind=ContactKind.COMPANY,
            company_name="OldVendor GmbH",
        )
        s.add(vendor)
        await s.commit()
        await s.refresh(vendor)
        cid = vendor.id

    last_year = date.today().year - 1
    await _add_invoice(
        sm,
        org_id=org.id,
        property_id=prop.id,
        contact_id=cid,
        issued=date(last_year, 5, 1),
        amount="500.00",
        name="old",
    )

    async with sm() as s:
        vendors = await load_vendors_for_property(s, property_id=prop.id)

    assert len(vendors) == 1
    # Invoice still listed + counted, but the current-year € total is 0.
    assert vendors[0].invoice_count == 1
    assert vendors[0].total_amount == Decimal("0")
    assert len(vendors[0].recent_invoices) == 1


async def test_reversed_invoices_hidden_from_owners_including_aggregates(
    test_engine: AsyncEngine,
) -> None:
    """A storno must not just drop out of the list — it must also stop
    counting toward invoice_count, the year total and the service dates.
    Otherwise an owner sees "3 Rechnungen" above a list of two."""
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    async with sm() as s:
        vendor = Contact(
            organization_id=org.id,
            kind=ContactKind.COMPANY,
            company_name="Keller GmbH",
        )
        s.add(vendor)
        await s.commit()
        await s.refresh(vendor)
        cid = vendor.id

    this_year = date.today().year
    await _add_invoice(
        sm,
        org_id=org.id,
        property_id=prop.id,
        contact_id=cid,
        issued=date(this_year, 3, 1),
        amount="100.00",
        name="gebucht",
        source_id=111,
    )
    # Cancelled: later date + bigger amount, so a leak would move BOTH
    # the total and last_service_date and the assertions would catch it.
    await _add_invoice(
        sm,
        org_id=org.id,
        property_id=prop.id,
        contact_id=cid,
        issued=date(this_year, 9, 1),
        amount="274.89",
        name="storniert",
        source_id=222,
    )

    async with sm() as s:
        owner_view = await load_vendors_for_property(
            s, property_id=prop.id, reversed_invoice_ids={222}
        )
        verwalter_view = await load_vendors_for_property(s, property_id=prop.id)

    assert len(owner_view) == 1
    owner = owner_view[0]
    assert [i.name for i in owner.recent_invoices] == ["gebucht"]
    assert owner.invoice_count == 1
    assert owner.total_amount == Decimal("100.00")
    assert owner.last_service_date == date(this_year, 3, 1)

    # The Verwalter keeps the full bookkeeping picture.
    assert verwalter_view[0].invoice_count == 2
    assert verwalter_view[0].total_amount == Decimal("374.89")


async def test_invoices_without_source_id_survive_the_storno_filter(
    test_engine: AsyncEngine,
) -> None:
    """`NULL NOT IN (...)` is NULL, not true — without an explicit NULL arm
    every locally-uploaded invoice (no Impower sourceId) would silently
    vanish from the vendor view the moment one storno existed."""
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    async with sm() as s:
        vendor = Contact(
            organization_id=org.id,
            kind=ContactKind.COMPANY,
            company_name="Lokal GmbH",
        )
        s.add(vendor)
        await s.commit()
        await s.refresh(vendor)
        cid = vendor.id

    this_year = date.today().year
    await _add_invoice(
        sm,
        org_id=org.id,
        property_id=prop.id,
        contact_id=cid,
        issued=date(this_year, 4, 1),
        amount="80.00",
        name="ohne-source-id",
    )

    async with sm() as s:
        vendors = await load_vendors_for_property(
            s, property_id=prop.id, reversed_invoice_ids={999}
        )

    assert len(vendors) == 1
    assert vendors[0].invoice_count == 1
    assert [i.name for i in vendors[0].recent_invoices] == ["ohne-source-id"]
