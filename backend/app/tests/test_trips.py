"""Fahrtenbuch API (ADR-0020): Verwalter-only, money math, admin totals + CSV."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.main import app
from app.models import UserRole
from app.tests._factories import make_org, make_property, make_user


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    token: str = r.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _complete_payload(**over: object) -> dict[str, object]:
    start = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)
    body: dict[str, object] = {
        "started_at": start.isoformat(),
        "ended_at": (start + timedelta(minutes=35)).isoformat(),
        "start_lat": "48.8120",
        "start_lng": "9.1720",
        "end_lat": "48.5970",
        "end_lng": "8.8700",
        "distance_m": 12_345,
        "source": "AUTO",
    }
    body.update(over)
    return body


async def test_owner_cannot_use_the_fahrtenbuch(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    _, email, pw = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=9500001
    )
    token = _login(email, pw)
    with TestClient(app) as client:
        assert client.get("/me/trips", headers=_auth(token)).status_code == 403
        assert client.get("/admin/trips", headers=_auth(token)).status_code == 403


async def test_complete_upload_confirms_and_prices_the_trip(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org, name="WEG Eibenweg 5/7")
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.post(
            "/me/trips/complete",
            headers=_auth(token),
            json=_complete_payload(purpose="BESICHTIGUNG", property_id=str(prop.id)),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "CONFIRMED"
        assert body["property_name"] == "WEG Eibenweg 5/7"
        assert body["distance_km"] == "12.3"
        # 12.345 km x 30 ct = 370.35 ct → 370 ct
        assert body["rate_cents_per_km"] == 30
        assert body["amount_cents"] == 370


async def test_complete_upload_without_purpose_is_open(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.post("/me/trips/complete", headers=_auth(token), json=_complete_payload())
        assert r.status_code == 201
        assert r.json()["status"] == "OPEN"
        tid = r.json()["id"]
        # Confirming the purpose later moves it to CONFIRMED.
        r2 = client.patch(f"/me/trips/{tid}", headers=_auth(token), json={"purpose": "ETV"})
        assert r2.status_code == 200
        assert r2.json()["status"] == "CONFIRMED"
        assert r2.json()["purpose"] == "ETV"


async def test_private_trip_earns_nothing(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.post(
            "/me/trips/complete", headers=_auth(token), json=_complete_payload(purpose="PRIVAT")
        )
        assert r.status_code == 201
        assert r.json()["amount_cents"] == 0
        assert r.json()["distance_km"] == "12.3"  # logged, just not paid


async def test_manual_start_is_idempotent_then_stop(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        a = client.post("/me/trips", headers=_auth(token), json={"source": "MANUAL"})
        assert a.status_code == 201
        assert a.json()["status"] == "RUNNING"
        # A second start while running must NOT fork the log.
        b = client.post("/me/trips", headers=_auth(token), json={"source": "MANUAL"})
        assert b.json()["id"] == a.json()["id"]
        assert client.get("/me/trips/running", headers=_auth(token)).json()["id"] == a.json()["id"]

        started = datetime.fromisoformat(a.json()["started_at"])
        stop = client.patch(
            f"/me/trips/{a.json()['id']}",
            headers=_auth(token),
            json={
                "ended_at": (started + timedelta(minutes=20)).isoformat(),
                "distance_m": 8_000,
                "purpose": "BUERO",
            },
        )
        assert stop.status_code == 200, stop.text
        assert stop.json()["status"] == "CONFIRMED"
        assert stop.json()["amount_cents"] == 240  # 8 km x 30 ct
        assert client.get("/me/trips/running", headers=_auth(token)).json() is None


async def test_end_before_start_is_rejected(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        bad = _complete_payload(ended_at=datetime(2026, 8, 21, 7, 0, tzinfo=UTC).isoformat())
        assert client.post("/me/trips/complete", headers=_auth(token), json=bad).status_code == 422


async def test_foreign_property_is_rejected(test_engine: AsyncEngine) -> None:
    org_a = await make_org(test_engine)
    org_b = await make_org(test_engine)
    foreign = await make_property(test_engine, org=org_b)
    _, email, pw = await make_user(test_engine, org=org_a, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.post(
            "/me/trips/complete",
            headers=_auth(token),
            json=_complete_payload(purpose="ETV", property_id=str(foreign.id)),
        )
        assert r.status_code == 400


async def test_drivers_only_see_their_own_trips(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    _, a_email, a_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    _, b_email, b_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    a_tok, b_tok = _login(a_email, a_pw), _login(b_email, b_pw)
    with TestClient(app) as client:
        r = client.post(
            "/me/trips/complete", headers=_auth(a_tok), json=_complete_payload(purpose="ETV")
        )
        tid = r.json()["id"]
        assert tid in {t["id"] for t in client.get("/me/trips", headers=_auth(a_tok)).json()}
        assert tid not in {t["id"] for t in client.get("/me/trips", headers=_auth(b_tok)).json()}
        # ...and B cannot edit or delete A's trip.
        assert (
            client.patch(f"/me/trips/{tid}", headers=_auth(b_tok), json={"note": "x"}).status_code
            == 404
        )
        assert client.delete(f"/me/trips/{tid}", headers=_auth(b_tok)).status_code == 404
        # The admin view does show both.
        admin = client.get("/admin/trips", headers=_auth(b_tok)).json()
        assert tid in {t["id"] for t in admin["items"]}


async def test_admin_totals_split_by_property_and_skip_private(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    p1 = await make_property(test_engine, org=org, name="WEG A")
    p2 = await make_property(test_engine, org=org, name="WEG B")
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        for payload in (
            _complete_payload(purpose="BESICHTIGUNG", property_id=str(p1.id), distance_m=10_000),
            _complete_payload(purpose="ETV", property_id=str(p1.id), distance_m=5_000),
            _complete_payload(
                purpose="HANDWERKERTERMIN", property_id=str(p2.id), distance_m=20_000
            ),
            _complete_payload(purpose="PRIVAT", distance_m=50_000),
        ):
            assert (
                client.post("/me/trips/complete", headers=_auth(token), json=payload).status_code
                == 201
            )

        r = client.get("/admin/trips", headers=_auth(token), params={"month": "2026-08"})
        assert r.status_code == 200, r.text
        body = r.json()
        s = body["summary"]
        assert s["trips"] == 4
        assert s["distance_m"] == 85_000  # private km are logged...
        assert s["billable_trips"] == 3
        assert s["billable_distance_m"] == 35_000  # ...but not billable
        assert s["amount_cents"] == 35 * 30

        by_prop = {p["property_name"]: p for p in body["by_property"]}
        assert by_prop["WEG A"]["trips"] == 2
        assert by_prop["WEG A"]["amount_cents"] == 15 * 30
        assert by_prop["WEG B"]["amount_cents"] == 20 * 30
        assert "(ohne Objekt)" not in by_prop  # the private trip is not an Auslage

        # Wrong month → nothing.
        empty = client.get("/admin/trips", headers=_auth(token), params={"month": "2026-07"}).json()
        assert empty["summary"]["trips"] == 0
        assert (
            client.get(
                "/admin/trips", headers=_auth(token), params={"month": "2026-13"}
            ).status_code
            == 400
        )


async def test_admin_csv_export_is_excel_de_friendly(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org, name="WEG Export")
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        client.post(
            "/me/trips/complete",
            headers=_auth(token),
            json=_complete_payload(purpose="ETV", property_id=str(prop.id), distance_m=12_345),
        )
        r = client.get("/admin/trips/export.csv", headers=_auth(token), params={"month": "2026-08"})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert 'filename="Fahrtenbuch-2026-08.csv"' in r.headers["content-disposition"]
        text = r.content.decode("utf-8-sig")  # BOM stripped by utf-8-sig
        lines = [ln for ln in text.splitlines() if ln]
        assert lines[0].startswith("Datum;Start;Ende;Fahrer;Objekt;Zweck;km;")
        row = next(ln for ln in lines if "WEG Export" in ln)
        assert ";12,3;30;3,70;AUTO;" in row  # decimal comma, 370 ct → 3,70 EUR
        assert lines[-1].startswith("Summe;")


async def test_admin_edit_is_audited(test_engine: AsyncEngine) -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models import AuditLog

    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org, name="WEG Audit")
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.post("/me/trips/complete", headers=_auth(token), json=_complete_payload())
        tid = r.json()["id"]
        e = client.patch(
            f"/admin/trips/{tid}",
            headers=_auth(token),
            json={"purpose": "EIGENTUEMERTERMIN", "property_id": str(prop.id)},
        )
        assert e.status_code == 200, e.text
        assert e.json()["status"] == "CONFIRMED"
        assert e.json()["property_name"] == "WEG Audit"

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        rows = (
            await s.scalars(
                select(AuditLog).where(AuditLog.action == "trip_edited", AuditLog.target_id == tid)
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].payload_json is not None
        assert rows[0].payload_json["before"]["purpose"] is None


async def test_statement_pdf_lists_trips_and_auslagen(test_engine: AsyncEngine) -> None:
    from io import BytesIO

    from pypdf import PdfReader

    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org, name="WEG Statement")
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        for payload in (
            _complete_payload(purpose="BESICHTIGUNG", property_id=str(prop.id), distance_m=10_000),
            _complete_payload(purpose="PRIVAT", distance_m=4_000),
        ):
            assert (
                client.post("/me/trips/complete", headers=_auth(token), json=payload).status_code
                == 201
            )
        r = client.get(
            "/admin/trips/statement.pdf", headers=_auth(token), params={"month": "2026-08"}
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("application/pdf")
        assert "Fahrtenbuch-2026-08-" in r.headers["content-disposition"]
        text = " ".join((p.extract_text() or "") for p in PdfReader(BytesIO(r.content)).pages)
        assert "August 2026" in text
        assert "WEG Statement" in text
        assert "Privat" in text
        # 10 km billable at 30 ct = 3,00 € total; private 4 km logged but 0 €.
        assert "3,00 €" in text
        assert "Auslagen je Objekt" in text
        # missing month → 422 (required query param)
        assert client.get("/admin/trips/statement.pdf", headers=_auth(token)).status_code == 422
