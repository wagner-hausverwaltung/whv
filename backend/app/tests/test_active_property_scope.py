"""Field surfaces only ever show objects WHV actively manages.

Two ways an object drops out: Impower "Abgegeben" (the sync soft-deletes it)
and state DRAFT (onboarding unfinished / object parked). Neither belongs in
the car — a manager should not be offered contacts, briefings, appointments
or caller-ID entries for an object he does not look after (Luis 2026-08-25).
The admin SPA keeps its own unfiltered queries, which this pins too.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.main import app
from app.models import (
    Contact,
    ContactKind,
    Contract,
    ContractContact,
    ContractType,
    Organization,
    Property,
    PropertyState,
    UserRole,
)
from app.tests._factories import make_org, make_property, make_unit, make_user
from app.tests.test_trips import _auth, _login


async def _link_contact(
    engine: AsyncEngine, *, org: Organization, prop: Property, name: str, phone: str
) -> None:
    """Give the property one owner with a phone number (caller ID + contacts)."""
    unit = await make_unit(engine, org=org, prop=prop)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        contact = Contact(
            organization_id=org.id,
            kind=ContactKind.PERSON,
            first_name="Test",
            last_name=name,
            email=f"{name.lower()}@example.de",
            phone=phone,
            impower_id=abs(hash(name)) % 1_000_000,
        )
        s.add(contact)
        await s.flush()
        contract = Contract(
            organization_id=org.id,
            property_id=prop.id,
            unit_id=unit.id,
            type=ContractType.OWNER,
        )
        s.add(contract)
        await s.flush()
        s.add(ContractContact(contract_id=contract.id, contact_id=contact.id))
        await s.commit()


async def test_draft_and_handed_over_objects_stay_out_of_the_car(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    ready = await make_property(test_engine, org=org, name="WEG Aktiv 1")
    draft = await make_property(test_engine, org=org, name="MV Entwurf 2")
    gone = await make_property(test_engine, org=org, name="MV Abgegeben 3")
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        d = await s.get(Property, draft.id)
        assert d is not None
        d.state = PropertyState.DRAFT
        g = await s.get(Property, gone.id)
        assert g is not None
        g.deleted_at = datetime.now(UTC)  # what the Impower sync does
        await s.commit()

    await _link_contact(test_engine, org=org, prop=ready, name="Aktiv", phone="+4971111111")
    await _link_contact(test_engine, org=org, prop=draft, name="Entwurf", phone="+4971122222")
    await _link_contact(test_engine, org=org, prop=gone, name="Abgegeben", phone="+4971133333")

    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        # 1. object list (CarPlay "Objekte", app picker)
        r = client.get("/me/properties", headers=_auth(token))
        assert r.status_code == 200
        names = {p["name"] for p in json.loads(r.text)}
        assert "WEG Aktiv 1" in names
        assert "MV Entwurf 2" not in names
        assert "MV Abgegeben 3" not in names

        # 2. Siri contact search ("WHV Notiz an …")
        r = client.get("/me/contacts/search", headers=_auth(token))
        assert r.status_code == 200
        found = {c["name"] for c in r.json()}
        assert any("Aktiv" in n for n in found)
        assert not any("Entwurf" in n for n in found)
        assert not any("Abgegeben" in n for n in found)

        # 3. caller ID list on the phone
        r = client.get("/me/call-directory", headers=_auth(token))
        assert r.status_code == 200
        labels = " ".join(e["label"] for e in r.json()["entries"])
        assert "Aktiv" in labels
        assert "Entwurf" not in labels
        assert "Abgegeben" not in labels

        # 4. briefing is refused for an object that is not managed
        assert (
            client.get(f"/me/properties/{draft.id}/briefing", headers=_auth(token)).status_code
            == 404
        )
        assert (
            client.get(f"/me/properties/{gone.id}/briefing", headers=_auth(token)).status_code
            == 404
        )
        assert (
            client.get(f"/me/properties/{ready.id}/briefing", headers=_auth(token)).status_code
            == 200
        )


async def test_agenda_skips_appointments_of_inactive_objects(test_engine: AsyncEngine) -> None:
    from app.models import CalendarEvent, CalendarEventType

    org = await make_org(test_engine)
    ready = await make_property(test_engine, org=org, name="WEG Termin aktiv")
    draft = await make_property(test_engine, org=org, name="WEG Termin Entwurf")
    starts = (datetime.now(UTC) + timedelta(days=2)).date()
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        d = await s.get(Property, draft.id)
        assert d is not None
        d.state = PropertyState.DRAFT
        for prop, title in ((ready, "Begehung aktiv"), (draft, "Begehung Entwurf")):
            s.add(
                CalendarEvent(
                    organization_id=org.id,
                    property_id=prop.id,
                    event_type=CalendarEventType.TERMIN,
                    title=title,
                    starts_on=starts,
                )
            )
        await s.commit()

    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.get("/me/agenda?days=14", headers=_auth(token))
        assert r.status_code == 200, r.text
        titles = {a["title"] for a in r.json()}
        assert "Begehung aktiv" in titles
        assert "Begehung Entwurf" not in titles


async def test_admin_still_sees_draft_objects_for_onboarding(test_engine: AsyncEngine) -> None:
    """The filter must not break onboarding: DRAFT stays visible in /admin."""
    org = await make_org(test_engine)
    draft = await make_property(test_engine, org=org, name="WEG Noch im Aufbau")
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        d = await s.get(Property, draft.id)
        assert d is not None
        d.state = PropertyState.DRAFT
        await s.commit()

    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.get("/admin/properties", headers=_auth(token))
        assert r.status_code == 200, r.text
        assert any(p["name"] == "WEG Noch im Aufbau" for p in r.json())
