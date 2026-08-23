"""Objekt-Briefing: spoken German summary of tickets, appointments, ETV,
Jahresabrechnung for the car (Verwalter-only)."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.main import app
from app.models import AssemblyStatus, EtvAssembly, PropertyType, UserRole
from app.tests._factories import make_org, make_property, make_user

_BERLIN = ZoneInfo("Europe/Berlin")


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    token: str = r.json()["access_token"]
    return token


async def test_briefing_reads_tickets_termine_and_etv(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    weg = await make_property(
        test_engine,
        org=org,
        name="WEG Hasenbergstraße 32, 70176 Stuttgart",
        type=PropertyType.OWNER,
    )
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    _, o_email, o_pw = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=7200001
    )
    today = datetime.now(_BERLIN).date()
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        s.add(
            EtvAssembly(
                organization_id=org.id,
                property_id=weg.id,
                title="ETV 2026",
                description="",
                status=AssemblyStatus.GEPLANT,
                scheduled_start=datetime.combine(
                    today + timedelta(days=3), time(18, 0), tzinfo=_BERLIN
                ),
                scheduled_end=datetime.combine(
                    today + timedelta(days=3), time(20, 0), tzinfo=_BERLIN
                ),
                location="Vor Ort",
            )
        )
        await s.commit()
    v_token, o_token = _login(v_email, v_pw), _login(o_email, o_pw)
    with TestClient(app) as client:
        h = {"Authorization": f"Bearer {v_token}"}
        # Two open tickets on the object.
        for subject in ("Kellerlicht defekt", "Haustür klemmt"):
            r = client.post(
                "/me/tickets",
                headers=h,
                json={
                    "subject": subject,
                    "body": "Bitte prüfen.",
                    "category": "SONSTIGES_OTHER",
                    "property_id": str(weg.id),
                },
            )
            assert r.status_code in (200, 201), r.text
        r = client.get(f"/me/properties/{weg.id}/briefing", headers=h)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["property_name"].startswith("WEG Hasenbergstraße 32")
        spoken = b["spoken"]
        assert spoken.startswith("Briefing WEG Hasenbergstraße 32")
        assert "2 offene Tickets" in spoken
        assert "Kellerlicht defekt" in spoken
        assert "ETV 2026" in spoken and "um 18 Uhr" in spoken
        assert "Nächste Versammlung" in spoken
        assert "Jahresabrechnung" in spoken
        titles = [sec["title"] for sec in b["sections"]]
        assert any(t.startswith("Offene Tickets") for t in titles)
        assert "Termine" in titles
        # Owners don't get the Verwalter briefing.
        assert (
            client.get(
                f"/me/properties/{weg.id}/briefing", headers={"Authorization": f"Bearer {o_token}"}
            ).status_code
            == 403
        )
