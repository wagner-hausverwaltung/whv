"""Offer generator — service + schema unit tests (no DB) and admin API tests.

The sync service/schema tests run anywhere; the async API tests exercise the
Verwalter-only POST /admin/offers/generate endpoint end-to-end.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.main import app
from app.models import OfferInquiry, Organization, UserRole
from app.schemas.offer import OfferGenerateRequest
from app.services.offer_pricing import price_offer
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


def test_weg_monthly_fee_override_bypasses_floor() -> None:
    # 6 units would normally hit the 270 € floor; an explicit fee wins.
    p = price_offer("WEG", units=6, start_date=_TODAY, monthly_fee_net_override=Decimal("300"))
    assert p.year1_monthly_net == Decimal("300.00")
    assert p.year1_monthly_gross == Decimal("357.00")  # 300 x 1.19
    assert p.floor_applied is False


def test_end_date_override_drives_term_and_schedule() -> None:
    p = price_offer(
        "WEG", units=6, start_date=date(2027, 1, 1), end_date_override=date(2029, 12, 31)
    )
    assert p.end_date == date(2029, 12, 31)
    assert p.term_years == 3  # ~3 whole years 01.01.2027 → 31.12.2029
    assert len(p.schedule) == 3


def test_end_date_must_be_after_start() -> None:
    with pytest.raises(ValueError):
        OfferGenerateRequest(
            art="WEG", units=5, start_date=date(2027, 1, 1), end_date=date(2026, 12, 31)
        )


def test_end_date_before_default_start_rejected() -> None:
    # start omitted (defaults to 1 Jan next year); a past end date must still fail
    # rather than slip through and print a backwards contract.
    with pytest.raises(ValueError):
        OfferGenerateRequest(art="WEG", units=5, end_date=date(2000, 1, 1))


def test_price_engine_rejects_end_before_start() -> None:
    with pytest.raises(ValueError):
        price_offer("WEG", units=5, start_date=date(2027, 1, 1), end_date_override=date(2026, 1, 1))


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


# --- detail, notes, re-download, reminder -------------------------------------


async def test_inquiry_detail_returns_body(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    inq = await _make_inquiry(test_engine, org)  # body == "x"
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.get(f"/admin/offer-inquiries/{inq.id}", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["body"] == "x"
    assert body["review_note"] is None
    assert body["reminder_count"] == 0


async def test_inquiry_detail_cross_org_404(test_engine: AsyncEngine) -> None:
    org_a = await make_org(test_engine)
    inq = await _make_inquiry(test_engine, org_a)
    org_b = await make_org(test_engine)
    _, email, pw = await make_user(test_engine, org=org_b, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.get(f"/admin/offer-inquiries/{inq.id}", headers=_auth(token))
    assert r.status_code == 404


async def test_inquiry_note_set_and_clear(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    inq = await _make_inquiry(test_engine, org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.put(
            f"/admin/offer-inquiries/{inq.id}/note",
            headers=_auth(token),
            json={"review_note": "Beirat zuerst fragen"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["review_note"] == "Beirat zuerst fragen"
        # Blank string clears it back to NULL.
        r2 = client.put(
            f"/admin/offer-inquiries/{inq.id}/note",
            headers=_auth(token),
            json={"review_note": "   "},
        )
    assert r2.json()["review_note"] is None


async def test_send_persists_request_and_enables_download(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    inq = await _make_inquiry(test_engine, org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        sent = client.post(
            f"/admin/offer-inquiries/{inq.id}/send", headers=_auth(token), json=_WEG_BODY
        )
        assert sent.status_code == 200, sent.text
        assert sent.json()["status"] == "SENT"
        assert sent.json()["generated_offer_filename"]
        # Re-download regenerates the as-sent PDF.
        pdf = client.get(f"/admin/offer-inquiries/{inq.id}/offer.pdf", headers=_auth(token))
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.content[:5] == b"%PDF-"
    assert "attachment" in pdf.headers.get("content-disposition", "")


async def test_send_with_price_and_date_overrides(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    inq = await _make_inquiry(test_engine, org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    body = {
        **_WEG_BODY,
        "start_date": "2026-01-01",
        "end_date": "2029-12-31",
        "monthly_fee_net_override": "333.00",
    }
    with TestClient(app) as client:
        sent = client.post(f"/admin/offer-inquiries/{inq.id}/send", headers=_auth(token), json=body)
        assert sent.status_code == 200, sent.text
        assert sent.json()["status"] == "SENT"
        # The override is captured in sent_request_json → re-download works.
        pdf = client.get(f"/admin/offer-inquiries/{inq.id}/offer.pdf", headers=_auth(token))
    assert pdf.status_code == 200, pdf.text
    assert pdf.content[:5] == b"%PDF-"


async def test_download_409_when_not_sent(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    inq = await _make_inquiry(test_engine, org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.get(f"/admin/offer-inquiries/{inq.id}/offer.pdf", headers=_auth(token))
    assert r.status_code == 409


async def test_reminder_requires_sent(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    inq = await _make_inquiry(test_engine, org)  # status NEW
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.post(f"/admin/offer-inquiries/{inq.id}/reminder", headers=_auth(token))
    assert r.status_code == 409


async def test_reminder_on_sent_stamps_count(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    inq = await _make_inquiry(test_engine, org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        client.post(
            f"/admin/offer-inquiries/{inq.id}/send", headers=_auth(token), json=_WEG_BODY
        ).raise_for_status()
        r = client.post(f"/admin/offer-inquiries/{inq.id}/reminder", headers=_auth(token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["reminder_count"] == 1
        assert body["last_reminder_at"] is not None
        # status stays SENT — a reminder must not corrupt the original send.
        assert body["status"] == "SENT"
        # Second reminder bumps the count again.
        r2 = client.post(f"/admin/offer-inquiries/{inq.id}/reminder", headers=_auth(token))
    assert r2.json()["reminder_count"] == 2


async def test_fields_update_persists(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    inq = await _make_inquiry(test_engine, org)  # art/units/object_address all NULL
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.put(
            f"/admin/offer-inquiries/{inq.id}/fields",
            headers=_auth(token),
            json={
                "art": "WEG",
                "object_address": "Musterstraße 12, 70123 Stuttgart",
                "units": 6,
                "desired_start": "2027-01-01",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["object_address"] == "Musterstraße 12, 70123 Stuttgart"
        # The correction shows in the list too.
        lst = client.get("/admin/offer-inquiries", headers=_auth(token))
    row = next(x for x in lst.json() if x["id"] == str(inq.id))
    assert row["art"] == "WEG"
    assert row["units"] == 6
    assert row["object_address"] == "Musterstraße 12, 70123 Stuttgart"


async def test_fields_update_validates_units(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    inq = await _make_inquiry(test_engine, org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.put(
            f"/admin/offer-inquiries/{inq.id}/fields",
            headers=_auth(token),
            json={"units": 0},  # below ge=1
        )
    assert r.status_code == 422


async def test_reminder_eigentuemer_forbidden(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    inq = await _make_inquiry(test_engine, org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.post(f"/admin/offer-inquiries/{inq.id}/reminder", headers=_auth(token))
    assert r.status_code == 403
