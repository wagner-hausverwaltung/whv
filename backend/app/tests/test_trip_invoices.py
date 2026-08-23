"""Auslagen-Rechnung je Objekt (ADR-0020 Phase 5): default rule, numbering,
snapshot + billed marking, PDF, cancel-only-latest."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any

from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncEngine

from app.main import app
from app.models import PropertyType, UserRole
from app.tests._factories import make_org, make_property, make_user


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    token: str = r.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _trip(client: TestClient, token: str, *, day: int, km: float, **over: Any) -> dict[str, Any]:
    start = datetime(2026, 8, day, 9, 0, tzinfo=UTC)
    body: dict[str, Any] = {
        "started_at": start.isoformat(),
        "ended_at": (start + timedelta(minutes=30)).isoformat(),
        "distance_m": int(km * 1000),
        "source": "MANUAL",
    }
    body.update(over)
    r = client.post("/me/trips/complete", headers=_auth(token), json=body)
    assert r.status_code == 201, r.text
    out: dict[str, Any] = r.json()
    return out


async def test_weg_invoice_flow(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    weg = await make_property(test_engine, org=org, name="WEG Rechnung", type=PropertyType.STRATA)
    other = await make_property(test_engine, org=org, name="WEG Andere")
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        etv = _trip(client, token, day=10, km=10, purpose="ETV", property_id=str(weg.id))
        hw = _trip(client, token, day=12, km=5, purpose="HANDWERKERTERMIN", property_id=str(weg.id))
        _trip(client, token, day=13, km=50, purpose="PRIVAT", property_id=str(weg.id))
        open_trip = _trip(client, token, day=14, km=3, property_id=str(weg.id))  # OPEN
        _trip(client, token, day=15, km=8, purpose="ETV", property_id=str(other.id))

        # Default rule for a WEG: only ETV pre-selected, 0,42 €/km.
        b = client.get(
            "/admin/trips/billable",
            headers=_auth(token),
            params={"property_id": str(weg.id), "until": "2026-08-31"},
        )
        assert b.status_code == 200, b.text
        billable = b.json()
        assert [i["id"] for i in billable["items"]] == [etv["id"], hw["id"]]
        assert billable["suggested_trip_ids"] == [etv["id"]]
        assert billable["rate_cents_per_km"] == 42
        assert "8.3.2" in billable["legal_basis"]
        assert open_trip["status"] == "OPEN"

        # Create: 10 km x 42 ct = 420 ct net, 19 % = 79,8 → 80 ct, gross 500.
        r = client.post(
            "/admin/trips/invoices",
            headers=_auth(token),
            json={
                "property_id": str(weg.id),
                "trip_ids": [etv["id"]],
                "rate_cents_per_km": 42,
                "issued_on": "2026-08-31",
            },
        )
        assert r.status_code == 201, r.text
        inv = r.json()
        assert inv["number"] == "WHV-FK-2026-0001"
        assert inv["net_cents"] == 420
        assert inv["vat_cents"] == 80
        assert inv["gross_cents"] == 500
        assert inv["trip_count"] == 1
        assert inv["property_name"] == "WEG Rechnung"
        assert inv["period_from"] == "2026-08-10" and inv["period_to"] == "2026-08-10"
        assert inv["cancellable"] is True

        # The trip is marked, billable shrinks, admin list shows the link.
        again = client.get(
            "/admin/trips/billable",
            headers=_auth(token),
            params={"property_id": str(weg.id), "until": "2026-08-31"},
        ).json()
        assert [i["id"] for i in again["items"]] == [hw["id"]]
        admin = client.get("/admin/trips", headers=_auth(token), params={"month": "2026-08"}).json()
        assert next(t for t in admin["items"] if t["id"] == etv["id"])["invoice_id"] == inv["id"]

        # Billing it twice is refused.
        dup = client.post(
            "/admin/trips/invoices",
            headers=_auth(token),
            json={"property_id": str(weg.id), "trip_ids": [etv["id"]], "rate_cents_per_km": 42},
        )
        assert dup.status_code == 409

        # PDF from the snapshot.
        pdf = client.get(f"/admin/trips/invoices/{inv['id']}/invoice.pdf", headers=_auth(token))
        assert pdf.status_code == 200
        assert pdf.content[:5] == b"%PDF-"
        text = "".join(p.extract_text() or "" for p in PdfReader(BytesIO(pdf.content)).pages)
        assert "WHV-FK-2026-0001" in text
        assert "Auslagenersatz" in text
        assert "DE367079394" in text  # USt-IdNr. in the footer
        assert "5,00" in text  # Rechnungsbetrag 5,00 €

        # Second invoice → 0002; now only that one is cancellable.
        r2 = client.post(
            "/admin/trips/invoices",
            headers=_auth(token),
            json={
                "property_id": str(weg.id),
                "trip_ids": [hw["id"]],
                "rate_cents_per_km": 50,
                "issued_on": "2026-08-31",
                "note": "Handwerkertermin außerhalb",
            },
        )
        assert r2.status_code == 201, r2.text
        inv2 = r2.json()
        assert inv2["number"] == "WHV-FK-2026-0002"
        assert inv2["net_cents"] == 250
        listing = client.get("/admin/trips/invoices", headers=_auth(token)).json()
        assert [i["number"] for i in listing] == ["WHV-FK-2026-0002", "WHV-FK-2026-0001"]
        assert [i["cancellable"] for i in listing] == [True, False]
        assert (
            client.delete(f"/admin/trips/invoices/{inv['id']}", headers=_auth(token)).status_code
            == 409
        )
        assert (
            client.delete(f"/admin/trips/invoices/{inv2['id']}", headers=_auth(token)).status_code
            == 204
        )
        # Its trip is free again and 0001 is now the latest.
        freed = client.get(
            "/admin/trips/billable",
            headers=_auth(token),
            params={"property_id": str(weg.id), "until": "2026-08-31"},
        ).json()
        assert [i["id"] for i in freed["items"]] == [hw["id"]]
        listing = client.get("/admin/trips/invoices", headers=_auth(token)).json()
        assert [(i["number"], i["cancellable"]) for i in listing] == [("WHV-FK-2026-0001", True)]


async def test_invoice_rejects_open_foreign_and_private(test_engine: AsyncEngine) -> None:
    org_a = await make_org(test_engine)
    org_b = await make_org(test_engine)
    prop = await make_property(test_engine, org=org_a, name="WEG A")
    foreign = await make_property(test_engine, org=org_b, name="WEG B")
    _, email, pw = await make_user(test_engine, org=org_a, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        open_trip = _trip(client, token, day=3, km=4, property_id=str(prop.id))
        private = _trip(client, token, day=4, km=4, purpose="PRIVAT", property_id=str(prop.id))
        base = {"property_id": str(prop.id), "rate_cents_per_km": 42}
        assert (
            client.post(
                "/admin/trips/invoices",
                headers=_auth(token),
                json={**base, "trip_ids": [open_trip["id"]]},
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/admin/trips/invoices",
                headers=_auth(token),
                json={**base, "trip_ids": [private["id"]]},
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/admin/trips/invoices",
                headers=_auth(token),
                json={
                    "property_id": str(foreign.id),
                    "trip_ids": [open_trip["id"]],
                    "rate_cents_per_km": 42,
                },
            ).status_code
            == 400
        )
        assert (
            client.get(
                "/admin/trips/billable",
                headers=_auth(token),
                params={"property_id": str(foreign.id)},
            ).status_code
            == 400
        )


async def test_mv_rule_preselects_nothing_at_fifty_cents(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    mv = await make_property(test_engine, org=org, name="MV Miete", type=PropertyType.RENTAL)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        t = _trip(client, token, day=5, km=12, purpose="EIGENTUEMERTERMIN", property_id=str(mv.id))
        b = client.get(
            "/admin/trips/billable", headers=_auth(token), params={"property_id": str(mv.id)}
        ).json()
        assert [i["id"] for i in b["items"]] == [t["id"]]
        assert b["suggested_trip_ids"] == []
        assert b["rate_cents_per_km"] == 50
        assert "5.4" in b["legal_basis"]
