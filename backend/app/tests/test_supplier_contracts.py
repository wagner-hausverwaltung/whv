"""Versorgungsverträge (supplier contracts) — Verwalter-only CRUD + scoping."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.main import app
from app.models import AuditLog, Meter, MeterType, UserRole
from app.tests._factories import make_org, make_property, make_user


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return str(r.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_meter(engine: AsyncEngine, org: Any, prop: Any) -> Meter:
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        meter = Meter(
            organization_id=org.id,
            property_id=prop.id,
            meter_number="1DZG0050069644",
            meter_type=MeterType.STROM,
        )
        s.add(meter)
        await s.commit()
        await s.refresh(meter)
    return meter


_BODY = {
    "category": "STROM",
    "provider_name": "EnBW",
    "contract_number": "V-2026-001",
    "customer_number": "K-777",
    "start_date": "2026-01-01",
    "end_date": "2027-12-31",
    "cancellation_months": 3,
    "auto_renew": True,
    "price": "85.50",
    "price_period": "MONATLICH",
    "notes": "Abschlag monatlich",
}


async def test_supplier_contract_crud_roundtrip(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org, name="Vertrag Haus")
    meter = await _make_meter(test_engine, org, prop)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)

    with TestClient(app) as client:
        # Create, linked to the property's meter.
        r = client.post(
            f"/admin/properties/{prop.id}/supplier-contracts",
            headers=_auth(token),
            json={**_BODY, "meter_id": str(meter.id)},
        )
        assert r.status_code == 201, r.text
        created = r.json()
        assert created["provider_name"] == "EnBW"
        assert created["meter_number"] == "1DZG0050069644"
        assert created["property_name"] == "Vertrag Haus"
        cid = created["id"]

        # Per-property list + org-wide board both show it.
        rl = client.get(f"/admin/properties/{prop.id}/supplier-contracts", headers=_auth(token))
        assert [x["id"] for x in rl.json()] == [cid]
        rb = client.get("/admin/supplier-contracts", headers=_auth(token))
        assert [x["id"] for x in rb.json()] == [cid]
        assert rb.json()[0]["property_name"] == "Vertrag Haus"

        # Update: change category + drop the meter link.
        ru = client.put(
            f"/admin/supplier-contracts/{cid}",
            headers=_auth(token),
            json={**_BODY, "category": "VERSICHERUNG", "provider_name": "AndSafe AG"},
        )
        assert ru.status_code == 200, ru.text
        assert ru.json()["category"] == "VERSICHERUNG"
        assert ru.json()["meter_id"] is None
        assert ru.json()["meter_number"] is None

        # Soft delete hides it from both lists.
        rd = client.delete(f"/admin/supplier-contracts/{cid}", headers=_auth(token))
        assert rd.status_code == 204
        assert (
            client.get(
                f"/admin/properties/{prop.id}/supplier-contracts", headers=_auth(token)
            ).json()
            == []
        )
        r404 = client.put(f"/admin/supplier-contracts/{cid}", headers=_auth(token), json=_BODY)
        assert r404.status_code == 404

    # Audit trail: created / updated / deleted.
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        actions = set(
            (await s.scalars(select(AuditLog.action).where(AuditLog.target_id == cid))).all()
        )
    assert actions == {
        "supplier_contract_created",
        "supplier_contract_updated",
        "supplier_contract_deleted",
    }


async def test_supplier_contract_meter_must_match_property(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop_a = await make_property(test_engine, org=org)
    prop_b = await make_property(test_engine, org=org)
    meter_b = await _make_meter(test_engine, org, prop_b)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.post(
            f"/admin/properties/{prop_a.id}/supplier-contracts",
            headers=_auth(token),
            json={**_BODY, "meter_id": str(meter_b.id)},
        )
    assert r.status_code == 400


async def test_supplier_contract_unknown_category_422(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.post(
            f"/admin/properties/{prop.id}/supplier-contracts",
            headers=_auth(token),
            json={**_BODY, "category": "PARKPLATZ"},
        )
    assert r.status_code == 422


async def test_supplier_contract_cross_org_404(test_engine: AsyncEngine) -> None:
    org_a = await make_org(test_engine)
    org_b = await make_org(test_engine)
    prop_a = await make_property(test_engine, org=org_a)
    _, email, pw = await make_user(test_engine, org=org_b, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.get(f"/admin/properties/{prop_a.id}/supplier-contracts", headers=_auth(token))
        assert r.status_code == 404
        rc = client.post(
            f"/admin/properties/{prop_a.id}/supplier-contracts",
            headers=_auth(token),
            json=_BODY,
        )
        assert rc.status_code == 404


async def test_supplier_contract_eigentuemer_forbidden(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.get("/admin/supplier-contracts", headers=_auth(token))
        assert r.status_code == 403
        rc = client.post(
            f"/admin/properties/{prop.id}/supplier-contracts",
            headers=_auth(token),
            json=_BODY,
        )
        assert rc.status_code == 403


async def test_supplier_contract_board_orders_by_end_date(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        for provider, end in (
            ("Später GmbH", "2030-12-31"),
            ("Bald AG", "2026-09-30"),
            ("Unbefristet KG", None),
        ):
            r = client.post(
                f"/admin/properties/{prop.id}/supplier-contracts",
                headers=_auth(token),
                json={**_BODY, "provider_name": provider, "end_date": end},
            )
            assert r.status_code == 201, r.text
        rb = client.get("/admin/supplier-contracts", headers=_auth(token))
    providers = [x["provider_name"] for x in rb.json()]
    # Soonest-ending first, open-ended last.
    assert providers == ["Bald AG", "Später GmbH", "Unbefristet KG"]


async def test_supplier_contract_status_roundtrip(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.post(
            f"/admin/properties/{prop.id}/supplier-contracts", headers=_auth(token), json=_BODY
        )
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "AKTIV"
        cid = r.json()["id"]

        ru = client.put(
            f"/admin/supplier-contracts/{cid}",
            headers=_auth(token),
            json={**_BODY, "status": "GEKUENDIGT"},
        )
        assert ru.status_code == 200, ru.text
        assert ru.json()["status"] == "GEKUENDIGT"

        rbad = client.put(
            f"/admin/supplier-contracts/{cid}",
            headers=_auth(token),
            json={**_BODY, "status": "PAUSIERT"},
        )
        assert rbad.status_code == 422


async def test_supplier_contract_documents_matched_by_provider(test_engine: AsyncEngine) -> None:
    from datetime import date as _date

    from app.tests._factories import make_document

    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    other_prop = await make_property(test_engine, org=org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)

    d_new = await make_document(
        test_engine, org=org, prop=prop, name="EnBW Jahresrechnung 2026.pdf"
    )
    d_old = await make_document(
        test_engine, org=org, prop=prop, name="EnBW Jahresrechnung 2025.pdf"
    )
    await make_document(test_engine, org=org, prop=prop, name="Techem Abrechnung.pdf")
    await make_document(test_engine, org=org, prop=other_prop, name="EnBW woanders.pdf")
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        from app.models import Document as _Document

        for did, day in ((d_new.id, _date(2026, 1, 15)), (d_old.id, _date(2025, 1, 15))):
            doc = await s.get(_Document, did)
            assert doc is not None
            doc.issued_date = day
        await s.commit()

    with TestClient(app) as client:
        r = client.post(
            f"/admin/properties/{prop.id}/supplier-contracts",
            headers=_auth(token),
            json={**_BODY, "provider_name": "EnBW Energie Baden-Württemberg AG"},
        )
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        rd = client.get(f"/admin/supplier-contracts/{cid}/documents", headers=_auth(token))
    assert rd.status_code == 200, rd.text
    names = [x["name"] for x in rd.json()]
    # Same property + provider token match only, newest first.
    assert names == ["EnBW Jahresrechnung 2026.pdf", "EnBW Jahresrechnung 2025.pdf"]


async def test_supplier_contract_documents_contact_linked_is_exclusive(
    test_engine: AsyncEngine,
) -> None:
    """A linked contact is authoritative: name-matched docs of OTHER vendors
    must not leak into the Belege list."""
    from app.models import Contact, ContactKind
    from app.tests._factories import make_document

    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        contact = Contact(
            organization_id=org.id, kind=ContactKind.COMPANY, company_name="Stadtwerke Ditzingen"
        )
        s.add(contact)
        await s.commit()
        await s.refresh(contact)

    linked_doc = await make_document(
        test_engine, org=org, prop=prop, name="Abschlag 2026.pdf", contact=contact
    )
    # Same property, name contains the shared city token — must NOT match.
    await make_document(test_engine, org=org, prop=prop, name="Grundsteuer Stadt Ditzingen.pdf")

    with TestClient(app) as client:
        r = client.post(
            f"/admin/properties/{prop.id}/supplier-contracts",
            headers=_auth(token),
            json={**_BODY, "provider_name": "Stadtwerke Ditzingen", "contact_id": str(contact.id)},
        )
        assert r.status_code == 201, r.text
        rd = client.get(
            f"/admin/supplier-contracts/{r.json()['id']}/documents", headers=_auth(token)
        )
    assert rd.status_code == 200, rd.text
    assert [x["id"] for x in rd.json()] == [str(linked_doc.id)]
