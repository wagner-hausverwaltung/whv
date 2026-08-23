"""Liegenschafts-Kalender (ADR-0018) — admin CRUD, merged ETV entries,
member read-only + scope, month PDF, and the end-before-start guard.
"""

import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.main import app
from app.models import AssemblyStatus, EtvAssembly, UserRole
from app.models.contract import ContractType
from app.tests._factories import (
    make_contact_with_contract_link,
    make_org,
    make_property,
    make_user,
)


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return str(r.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _unique_impower() -> int:
    return uuid.uuid4().int % 2_000_000_000


async def _setup(engine: AsyncEngine) -> dict[str, Any]:
    org = await make_org(engine)
    _, v_email, v_pw = await make_user(engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(engine, org=org)
    imp = _unique_impower()
    _, m_email, m_pw = await make_user(
        engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=imp
    )
    await make_contact_with_contract_link(
        engine, org=org, prop=prop, contact_impower_id=imp, contract_type=ContractType.OWNER
    )
    return {
        "org": org,
        "prop": prop,
        "v_token": _login(v_email, v_pw),
        "m_token": _login(m_email, m_pw),
    }


async def _make_assembly(
    engine: AsyncEngine,
    *,
    org: Any,
    prop: Any,
    when: datetime,
    status: AssemblyStatus = AssemblyStatus.GEPLANT,
    title: str = "ETV 2026",
) -> EtvAssembly:
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        a = EtvAssembly(
            organization_id=org.id,
            property_id=prop.id,
            title=title,
            description="",
            status=status,
            scheduled_start=when,
            scheduled_end=when,
            location="Vor Ort",
        )
        s.add(a)
        await s.commit()
        await s.refresh(a)
    return a


def _create_event(client: TestClient, token: str, pid: uuid.UUID, **over: Any) -> Any:
    body: dict[str, Any] = {
        "event_type": "WINTERDIENST",
        "starts_on": "2026-06-15",
        "assigned_label": "Familie Müller",
    }
    body.update(over)
    return client.post(f"/admin/properties/{pid}/calendar/events", headers=_auth(token), json=body)


async def test_admin_create_and_list_event(test_engine: AsyncEngine) -> None:
    ctx = await _setup(test_engine)
    pid = ctx["prop"].id
    with TestClient(app) as client:
        r = _create_event(client, ctx["v_token"], pid)
        assert r.status_code == 201, r.text
        ev = r.json()
        assert ev["event_type"] == "WINTERDIENST"

        r_cal = client.get(
            f"/admin/properties/{pid}/calendar?year=2026&month=6", headers=_auth(ctx["v_token"])
        )
        assert r_cal.status_code == 200
        entries = r_cal.json()
        match = [e for e in entries if e["source"] == "event" and e["id"] == ev["id"]]
        assert len(match) == 1
        assert match[0]["kind"] == "WINTERDIENST"
        assert match[0]["assigned_label"] == "Familie Müller"


async def test_etv_appears_in_calendar(test_engine: AsyncEngine) -> None:
    ctx = await _setup(test_engine)
    pid = ctx["prop"].id
    await _make_assembly(
        test_engine, org=ctx["org"], prop=ctx["prop"], when=datetime(2026, 6, 20, 10, 0, tzinfo=UTC)
    )
    with TestClient(app) as client:
        # member sees the ETV entry in their read-only calendar
        r = client.get(
            f"/me/properties/{pid}/calendar?year=2026&month=6", headers=_auth(ctx["m_token"])
        )
        assert r.status_code == 200, r.text
        etv = [e for e in r.json() if e["source"] == "etv"]
        assert len(etv) == 1
        assert etv[0]["kind"] == "ETV"
        assert etv[0]["assembly_id"]
        # a different month has no ETV entry
        r2 = client.get(
            f"/me/properties/{pid}/calendar?year=2026&month=7", headers=_auth(ctx["m_token"])
        )
        assert all(e["source"] != "etv" for e in r2.json())


async def test_update_and_delete_event(test_engine: AsyncEngine) -> None:
    ctx = await _setup(test_engine)
    pid = ctx["prop"].id
    with TestClient(app) as client:
        ev = _create_event(client, ctx["v_token"], pid).json()
        r_up = client.patch(
            f"/admin/calendar/events/{ev['id']}",
            headers=_auth(ctx["v_token"]),
            json={"assigned_label": "Hausmeister Schmidt", "ends_on": "2026-06-21"},
        )
        assert r_up.status_code == 200
        assert r_up.json()["assigned_label"] == "Hausmeister Schmidt"
        assert r_up.json()["ends_on"] == "2026-06-21"

        r_del = client.delete(f"/admin/calendar/events/{ev['id']}", headers=_auth(ctx["v_token"]))
        assert r_del.status_code == 204


async def test_end_before_start_rejected(test_engine: AsyncEngine) -> None:
    ctx = await _setup(test_engine)
    pid = ctx["prop"].id
    with TestClient(app) as client:
        r = _create_event(client, ctx["v_token"], pid, starts_on="2026-06-15", ends_on="2026-06-10")
        assert r.status_code == 400


async def test_calendar_pdf(test_engine: AsyncEngine) -> None:
    ctx = await _setup(test_engine)
    pid = ctx["prop"].id
    with TestClient(app) as client:
        _create_event(client, ctx["v_token"], pid, event_type="KEHRWOCHE", starts_on="2026-06-03")
        r = client.get(
            f"/admin/properties/{pid}/calendar.pdf?year=2026&month=6", headers=_auth(ctx["v_token"])
        )
        assert r.status_code == 200
        assert "application/pdf" in r.headers["content-type"]
        assert r.content[:5] == b"%PDF-"


async def test_calendar_ics_export(test_engine: AsyncEngine) -> None:
    ctx = await _setup(test_engine)
    pid = ctx["prop"].id
    await _make_assembly(
        test_engine, org=ctx["org"], prop=ctx["prop"], when=datetime(2026, 7, 15, 13, 0, tzinfo=UTC)
    )
    with TestClient(app) as client:
        _create_event(client, ctx["v_token"], pid, event_type="KEHRWOCHE", starts_on="2026-06-03")
        r = client.get(f"/me/properties/{pid}/calendar.ics", headers=_auth(ctx["m_token"]))
        assert r.status_code == 200, r.text
        assert "text/calendar" in r.headers["content-type"]
        body = r.text
        assert body.startswith("BEGIN:VCALENDAR")
        assert "END:VCALENDAR" in body
        assert "\r\n" in body  # RFC 5545 line endings
        # ETV → timed VEVENT (real start/end + location)
        assert "UID:etv-" in body
        assert "DTSTART:20260715T130000Z" in body
        assert "SUMMARY:ETV: ETV 2026" in body
        assert "LOCATION:Vor Ort" in body
        # stored event → all-day VEVENT, end date exclusive
        assert "UID:event-" in body
        assert "DTSTART;VALUE=DATE:20260603" in body
        assert "DTEND;VALUE=DATE:20260604" in body

    # cross-org: an org-B member can't export org-A's property calendar
    ctx_b = await _setup(test_engine)
    with TestClient(app) as client:
        assert (
            client.get(
                f"/me/properties/{pid}/calendar.ics", headers=_auth(ctx_b["m_token"])
            ).status_code
            == 404
        )


async def test_member_cannot_create_and_cross_org_isolation(test_engine: AsyncEngine) -> None:
    ctx_a = await _setup(test_engine)
    ctx_b = await _setup(test_engine)
    pid_a = ctx_a["prop"].id
    with TestClient(app) as client:
        # member (non-Verwalter) can't hit the admin create endpoint
        assert _create_event(client, ctx_a["m_token"], pid_a).status_code == 403
        # org B Verwalter can't read org A's calendar
        assert (
            client.get(
                f"/admin/properties/{pid_a}/calendar?year=2026&month=6",
                headers=_auth(ctx_b["v_token"]),
            ).status_code
            == 404
        )


# --- /me/agenda (Verwalter: ETV + Termine org-weit, für CarPlay "Heute") -----

_BERLIN = ZoneInfo("Europe/Berlin")


async def test_agenda_lists_etv_and_termine_across_properties(test_engine: AsyncEngine) -> None:
    ctx = await _setup(test_engine)
    org, prop = ctx["org"], ctx["prop"]
    other = await make_property(test_engine, org=org, name="WEG Agenda B")
    today = datetime.now(_BERLIN).date()
    tomorrow_18 = datetime.combine(today + timedelta(days=1), time(18, 0), tzinfo=_BERLIN)
    etv = await _make_assembly(test_engine, org=org, prop=prop, when=tomorrow_18)
    # Excluded: cancelled, and beyond the 7-day window.
    await _make_assembly(
        test_engine,
        org=org,
        prop=prop,
        when=tomorrow_18,
        status=AssemblyStatus.ABGESAGT,
        title="Abgesagt",
    )
    await _make_assembly(
        test_engine, org=org, prop=other, when=tomorrow_18 + timedelta(days=20), title="Spaeter"
    )
    with TestClient(app) as client:
        assert (
            _create_event(
                client,
                ctx["v_token"],
                other.id,
                event_type="TERMIN",
                title="Handwerker Dach",
                starts_on=today.isoformat(),
                assigned_label=None,
            ).status_code
            == 201
        )
        # Kehrwoche is an owner duty, not a Verwalter appointment.
        assert (
            _create_event(
                client,
                ctx["v_token"],
                prop.id,
                event_type="KEHRWOCHE",
                starts_on=today.isoformat(),
            ).status_code
            == 201
        )

        r = client.get("/me/agenda", headers=_auth(ctx["v_token"]), params={"days": 7})
        assert r.status_code == 200, r.text
        items = r.json()
        assert [(i["kind"], i["title"]) for i in items] == [
            ("TERMIN", "Handwerker Dach"),
            ("ETV", "ETV 2026"),
        ]
        termin, etv_item = items
        assert termin["all_day"] is True
        assert termin["property_name"] == "WEG Agenda B"
        assert termin["property_id"] == str(other.id)
        assert etv_item["all_day"] is False
        assert etv_item["location"] == "Vor Ort"
        assert etv_item["assembly_id"] == str(etv.id)
        assert datetime.fromisoformat(etv_item["starts_at"]).astimezone(_BERLIN).hour == 18
        assert etv_item["property_address"]  # street/city from the factory

        # One property only.
        only = client.get(
            "/me/agenda",
            headers=_auth(ctx["v_token"]),
            params={"days": 7, "property_id": str(prop.id)},
        ).json()
        assert [i["kind"] for i in only] == ["ETV"]
        # Wider window picks up the later ETV; days=0 is just today.
        wide = client.get("/me/agenda", headers=_auth(ctx["v_token"]), params={"days": 30}).json()
        assert "Spaeter" in {i["title"] for i in wide}
        today_only = client.get(
            "/me/agenda", headers=_auth(ctx["v_token"]), params={"days": 0}
        ).json()
        assert [i["kind"] for i in today_only] == ["TERMIN"]

        # Owners don't get the Verwalter agenda.
        assert client.get("/me/agenda", headers=_auth(ctx["m_token"])).status_code == 403
