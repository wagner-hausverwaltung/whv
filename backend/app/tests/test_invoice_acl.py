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

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.api.v1.me import _document_visibility_filter, _invoice_visibility_filter
from app.config import get_settings
from app.main import app
from app.models import Contact, ContactKind, Document, DocumentKind, UserRole
from app.services.invoice_cache import get_invoice_cache
from app.services.reversed_invoices import get_reversed_invoice_cache
from app.tests._factories import (
    make_contact_with_contract_link,
    make_document,
    make_org,
    make_property,
    make_unit,
    make_user,
)

# Distinctive impower id — the session test DB keeps committed rows, so this
# must not collide with another test's contact (contacts.impower_id is unique).
_OWNER_IMPOWER_ID = 9300042
_REVERSED_OWNER_IMPOWER_ID = 9300043
_DOWNLOAD_OWNER_IMPOWER_ID = 9300044
_STORNO_PROPERTY_IMPOWER_ID = 9300777


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return str(r.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_owner_sees_weg_vendor_invoice_but_not_scoped_one(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    # Owner: Contact + active OWNER contract on their unit.
    owner_unit = await make_unit(test_engine, org=org, prop=prop)
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=_OWNER_IMPOWER_ID, unit=owner_unit
    )
    owner, _, _ = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=_OWNER_IMPOWER_ID
    )

    # Vendor contact (no contract of its own).
    async with sm() as s:
        vendor = Contact(organization_id=org.id, kind=ContactKind.COMPANY, company_name="Acme GmbH")
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

    async with sm() as s:
        old_visible = set(
            (
                await s.scalars(
                    select(Document.id).where(
                        Document.property_id == prop.id,
                        _document_visibility_filter(owner),
                    )
                )
            ).all()
        )
        new_visible = set(
            (
                await s.scalars(
                    select(Document.id).where(
                        Document.property_id == prop.id,
                        _invoice_visibility_filter(owner),
                    )
                )
            ).all()
        )

    # The OLD generic filter hid the WEG vendor invoice — that was the bug.
    assert weg_invoice.id not in old_visible
    # The invoice-aware filter surfaces it…
    assert weg_invoice.id in new_visible
    # …but a unit-pinned invoice on a unit the owner isn't on stays hidden.
    assert scoped_invoice.id not in new_visible


async def test_owner_cannot_open_a_reversed_invoice_but_verwalter_can(
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Storno bookings are filtered out of the vendor list, so the detail
    must refuse them too — a stale client, a bookmarked id or a
    cancellation that lands after the list was rendered would otherwise
    still surface an invoice the WEG never owed. Verwalter keep access."""
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    owner_unit = await make_unit(test_engine, org=org, prop=prop)
    await make_contact_with_contract_link(
        test_engine,
        org=org,
        prop=prop,
        contact_impower_id=_REVERSED_OWNER_IMPOWER_ID,
        unit=owner_unit,
    )
    _, owner_email, owner_pw = await make_user(
        test_engine,
        org=org,
        role=UserRole.EIGENTUEMER,
        contact_id_impower=_REVERSED_OWNER_IMPOWER_ID,
    )
    _, verwalter_email, verwalter_pw = await make_user(
        test_engine, org=org, role=UserRole.VERWALTER
    )

    async with sm() as s:
        vendor = Contact(
            organization_id=org.id, kind=ContactKind.COMPANY, company_name="Keller GmbH"
        )
        s.add(vendor)
        await s.commit()
        await s.refresh(vendor)

    doc = await make_document(
        test_engine, org=org, prop=prop, kind=DocumentKind.RECHNUNG, contact=vendor
    )
    invoice_id = 77_000_042
    async with sm() as s:
        row = await s.get(Document, doc.id)
        assert row is not None
        row.raw_jsonb = {"sourceId": invoice_id}
        await s.commit()

    settings = get_settings()
    monkeypatch.setattr(settings, "impower_api_token", "test-token", raising=False)

    # Seed the cache so the endpoint never reaches out to Impower.
    cache = get_invoice_cache()
    await cache.set(invoice_id, {"state": "REVERSED", "invoiceNumber": "202480670"})
    try:
        owner_token = _login(owner_email, owner_pw)
        verwalter_token = _login(verwalter_email, verwalter_pw)
        url = f"/me/properties/{prop.id}/invoices/{doc.id}"
        with TestClient(app) as client:
            owner_res = client.get(url, headers=_auth(owner_token))
            verwalter_res = client.get(url, headers=_auth(verwalter_token))
    finally:
        await cache.clear()

    assert owner_res.status_code == 404, owner_res.text
    assert verwalter_res.status_code == 200, verwalter_res.text
    assert verwalter_res.json()["state"] == "REVERSED"


async def test_owner_cannot_download_a_reversed_invoice_pdf(
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bytes are the leak, not just the booking detail: hiding the row
    and 404ing the dialog is worthless if /file still serves the PDF."""
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org, impower_id=_STORNO_PROPERTY_IMPOWER_ID)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    owner_unit = await make_unit(test_engine, org=org, prop=prop)
    await make_contact_with_contract_link(
        test_engine,
        org=org,
        prop=prop,
        contact_impower_id=_DOWNLOAD_OWNER_IMPOWER_ID,
        unit=owner_unit,
    )
    _, owner_email, owner_pw = await make_user(
        test_engine,
        org=org,
        role=UserRole.EIGENTUEMER,
        contact_id_impower=_DOWNLOAD_OWNER_IMPOWER_ID,
    )

    async with sm() as s:
        vendor = Contact(
            organization_id=org.id, kind=ContactKind.COMPANY, company_name="Keller GmbH"
        )
        s.add(vendor)
        await s.commit()
        await s.refresh(vendor)

    doc = await make_document(
        test_engine, org=org, prop=prop, kind=DocumentKind.RECHNUNG, contact=vendor
    )
    invoice_id = 77_000_099
    async with sm() as s:
        row = await s.get(Document, doc.id)
        assert row is not None
        row.raw_jsonb = {"sourceId": invoice_id}
        await s.commit()

    # Seed the storno set directly — no Impower round-trip in the test.
    cache = get_reversed_invoice_cache()
    async with cache._lock:
        cache._store[_STORNO_PROPERTY_IMPOWER_ID] = (time.monotonic() + 600, {invoice_id})
    try:
        token = _login(owner_email, owner_pw)
        with TestClient(app) as client:
            res = client.get(f"/me/documents/{doc.id}/file", headers=_auth(token))
    finally:
        await cache.clear()

    assert res.status_code == 404, res.text
