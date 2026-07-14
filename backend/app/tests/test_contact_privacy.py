"""Privacy gate on GET /me/contracts/{id}/contacts/{id}: the full card
(Geburtsdatum, Anschrift, SEPA-Mandat, E-Mail, Telefon, USt-ID) is
"see your own data" — co-owners only get the identity line."""

from __future__ import annotations

import itertools
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.main import app
from app.models import Contact, Contract, Organization, Property, UserRole
from app.tests._factories import (
    make_contact_with_contract_link,
    make_org,
    make_property,
    make_user,
)

SENSITIVE = (
    "date_of_birth",
    "vat_id",
    "trade_register_number",
    "recipient_name",
    "mandate_number",
    "email",
    "phone",
    "additional_contacts",
    "city",
    "street",
    "number",
    "postal_code",
    "country",
)


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return str(r.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


_IDS = itertools.count(95001, 2)


async def _setup(
    test_engine: AsyncEngine,
) -> tuple[Organization, Property, Contact, Contract, int, int]:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    id_a = next(_IDS)
    id_b = id_a + 1
    contact_a, contract_a = await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=id_a
    )
    await make_contact_with_contract_link(test_engine, org=org, prop=prop, contact_impower_id=id_b)
    # Give A's contact the full PII set a real Impower sync carries.
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        await s.execute(
            update(Contact)
            .where(Contact.id == contact_a.id)
            .values(
                date_of_birth=date(1960, 5, 17),
                street="Geheimweg",
                number="1",
                postal_code="70000",
                city="Stuttgart",
                mandate_number="SEPA-XYZ-123",
                email="owner-a@example.com",
                phone="0711 123456",
                vat_id="DE999999999",
            )
        )
        await s.commit()
    return org, prop, contact_a, contract_a, id_a, id_b


async def test_co_owner_gets_redacted_card(test_engine: AsyncEngine) -> None:
    org, _prop, contact_a, contract_a, _id_a, id_b = await _setup(test_engine)
    _, b_email, b_pw = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=id_b
    )
    token = _login(b_email, b_pw)
    with TestClient(app) as client:
        r = client.get(
            f"/me/contracts/{contract_a.id}/contacts/{contact_a.id}", headers=_auth(token)
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["first_name"] == "Test"
    assert body["last_name"] is not None
    for field in SENSITIVE:
        assert body[field] is None, f"{field} leaked to co-owner: {body[field]!r}"


async def test_self_gets_full_card(test_engine: AsyncEngine) -> None:
    org, _prop, contact_a, contract_a, id_a, _id_b = await _setup(test_engine)
    _, a_email, a_pw = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=id_a
    )
    token = _login(a_email, a_pw)
    with TestClient(app) as client:
        r = client.get(
            f"/me/contracts/{contract_a.id}/contacts/{contact_a.id}", headers=_auth(token)
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["date_of_birth"] == "1960-05-17"
    assert body["mandate_number"] == "SEPA-XYZ-123"
    assert body["street"] == "Geheimweg"
    assert body["email"] == "owner-a@example.com"


async def test_verwalter_gets_full_card(test_engine: AsyncEngine) -> None:
    org, _prop, contact_a, contract_a, _id_a, _id_b = await _setup(test_engine)
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(v_email, v_pw)
    with TestClient(app) as client:
        r = client.get(
            f"/me/contracts/{contract_a.id}/contacts/{contact_a.id}", headers=_auth(token)
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["date_of_birth"] == "1960-05-17"
    assert body["mandate_number"] == "SEPA-XYZ-123"
