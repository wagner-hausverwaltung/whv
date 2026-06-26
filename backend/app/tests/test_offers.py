"""Offer generator — service + schema unit tests (no DB) and admin API tests.

The sync service/schema tests run anywhere; the async API tests exercise the
Verwalter-only POST /admin/offers/generate endpoint end-to-end.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.main import app
from app.models import OfferInquiry, Organization, UserRole
from app.schemas.offer import OfferGenerateRequest
from app.services.offers import generate_offer
from app.tests._factories import make_org, make_property, make_user


async def _make_inquiry(engine: AsyncEngine, org: Organization) -> OfferInquiry:
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        inq = OfferInquiry(
            organization_id=org.id, sender_email="prospect@example.com", subject="Anfrage", body="x"
        )
        s.add(inq)
        await s.commit()
        await s.refresh(inq)
    return inq


_TODAY = date(2026, 6, 25)


# --- service + schema (no DB) -------------------------------------------------


def test_generate_weg_pdf() -> None:
    req = OfferGenerateRequest(
        art="WEG", units=8, object_street="Teststraße 4", object_plz_city="70000 Teststadt"
    )
    pdf, name = generate_offer(req, today=_TODAY)
    assert pdf[:5] == b"%PDF-"
    assert name.startswith("Angebot-WEG-") and name.endswith(".pdf")


def test_generate_mv_pdf() -> None:
    req = OfferGenerateRequest(
        art="MV",
        units=10,
        recipient_name="Max Mustermann",
        recipient_street="Weg 1",
        recipient_plz_city="70000 Stuttgart",
        salutation="Sehr geehrter Herr Mustermann,",
        objects=["Haus A, 70000 Stuttgart"],
    )
    pdf, name = generate_offer(req, today=_TODAY)
    assert pdf[:5] == b"%PDF-"
    assert name.startswith("Angebot-MV-")


def test_weg_object_address_optional() -> None:
    # WEG offers no longer require an object address — only the unit count.
    req = OfferGenerateRequest(art="WEG", units=5)
    assert req.object_street is None
    assert req.object_plz_city is None


def test_mv_requires_recipient_and_objects() -> None:
    with pytest.raises(ValueError):
        OfferGenerateRequest(art="MV", units=5, recipient_name="X")


def test_mv_rejects_more_than_three_objects() -> None:
    with pytest.raises(ValueError):
        OfferGenerateRequest(
            art="MV",
            units=5,
            recipient_name="X",
            recipient_street="Y",
            recipient_plz_city="Z",
            salutation="Hallo,",
            objects=["a", "b", "c", "d"],
        )


# --- admin API ----------------------------------------------------------------


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return str(r.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


_WEG_BODY = {
    "art": "WEG",
    "units": 6,
    "object_street": "Musterstraße 12",
    "object_plz_city": "70123 Stuttgart",
}


async def test_generate_offer_requires_auth(test_engine: AsyncEngine) -> None:
    with TestClient(app) as client:
        r = client.post("/admin/offers/generate", json=_WEG_BODY)
    assert r.status_code == 401


async def test_eigentuemer_forbidden(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.post("/admin/offers/generate", headers=_auth(token), json=_WEG_BODY)
    assert r.status_code == 403


async def test_verwalter_generates_weg_pdf(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    await make_property(test_engine, org=org)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.post("/admin/offers/generate", headers=_auth(token), json=_WEG_BODY)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content[:5] == b"%PDF-"
    assert "attachment" in r.headers.get("content-disposition", "")


async def test_verwalter_weg_without_address_ok(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        # No object address — WEG only needs units; should still render a PDF.
        r = client.post(
            "/admin/offers/generate", headers=_auth(token), json={"art": "WEG", "units": 5}
        )
    assert r.status_code == 200, r.text
    assert r.content[:5] == b"%PDF-"


async def test_verwalter_mv_missing_fields_422(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.post(
            "/admin/offers/generate",
            headers=_auth(token),
            json={"art": "MV", "units": 5},  # missing recipient/objects -> schema rejects
        )
    assert r.status_code == 422


# --- Auto-Modus settings ------------------------------------------------------


async def test_offer_settings_default_false(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.get("/admin/offer-settings", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["auto_send_enabled"] is False


async def test_offer_settings_put_persists(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.put(
            "/admin/offer-settings", headers=_auth(token), json={"auto_send_enabled": True}
        )
        assert r.status_code == 200, r.text
        assert r.json()["auto_send_enabled"] is True
        r2 = client.get("/admin/offer-settings", headers=_auth(token))
    assert r2.json()["auto_send_enabled"] is True


async def test_offer_settings_eigentuemer_forbidden(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.put(
            "/admin/offer-settings", headers=_auth(token), json={"auto_send_enabled": True}
        )
    assert r.status_code == 403


# --- per-offer lead status ----------------------------------------------------


async def test_lead_status_defaults_open(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    inq = await _make_inquiry(test_engine, org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.get("/admin/offer-inquiries", headers=_auth(token))
    assert r.status_code == 200, r.text
    row = next(x for x in r.json() if x["id"] == str(inq.id))
    assert row["lead_status"] == "OPEN"


async def test_lead_status_update(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    inq = await _make_inquiry(test_engine, org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.put(
            f"/admin/offer-inquiries/{inq.id}/lead-status",
            headers=_auth(token),
            json={"lead_status": "ACCEPTED"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["lead_status"] == "ACCEPTED"


async def test_lead_status_invalid_422(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    inq = await _make_inquiry(test_engine, org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.put(
            f"/admin/offer-inquiries/{inq.id}/lead-status",
            headers=_auth(token),
            json={"lead_status": "MAYBE"},
        )
    assert r.status_code == 422


async def test_lead_status_eigentuemer_forbidden(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    inq = await _make_inquiry(test_engine, org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.put(
            f"/admin/offer-inquiries/{inq.id}/lead-status",
            headers=_auth(token),
            json={"lead_status": "ACCEPTED"},
        )
    assert r.status_code == 403
