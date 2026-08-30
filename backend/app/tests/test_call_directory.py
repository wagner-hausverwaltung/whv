"""Caller ID list for the iOS Call Directory Extension: normalisation, labels,
dedupe, ordering, role gate."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.api.v1.call_directory import build_label, normalize_phone, short_property_name
from app.main import app
from app.models import Contact, UserRole
from app.models.contract import ContractType
from app.tests._factories import make_contact_with_contract_link, make_org, make_property, make_user


def test_normalize_phone_variants() -> None:
    assert normalize_phone("+49 711 123-45") == 4971112345
    assert normalize_phone("0711/12345") == 4971112345
    assert normalize_phone("0049 711 12345") == 4971112345
    assert normalize_phone("0176 1234567") == 491761234567
    assert normalize_phone("+41 44 123 45 67") == 41441234567
    assert normalize_phone("0711 12345 Durchwahl 12") == 4971112345
    assert normalize_phone("") is None
    assert normalize_phone("-") is None
    assert normalize_phone("12") is None


def test_label_shape() -> None:
    assert short_property_name("WEG Hasenbergstraße 32, 70176 Stuttgart") == "WEG Hasenbergstr. 32"
    one = build_label(
        "Franziska Fritz", [("WEG Hasenbergstraße 32, 70176 Stuttgart", "Eigentümer")]
    )
    assert one == "Franziska Fritz · WEG Hasenbergstr. 32 (Eigentümer)"
    two = build_label("F. Fritz", [("WEG A, 1 X", "Eigentümer"), ("MV B, 2 Y", "Mieter")])
    assert two.endswith(" +1")
    assert len(build_label("X" * 80, [("WEG A", "Eigentümer")])) <= 60


async def _set_phone(engine: AsyncEngine, contact_id: uuid.UUID, phone: str) -> None:
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        await s.execute(update(Contact).where(Contact.id == contact_id).values(phone=phone))
        await s.commit()


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    token: str = r.json()["access_token"]
    return token


async def test_call_directory_lists_contacts_with_phone(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    weg = await make_property(test_engine, org=org, name="WEG Hasenbergstraße 32, 70176 Stuttgart")
    mv = await make_property(test_engine, org=org, name="MV Karlstraße 5, 71696 Möglingen")
    owner, _ = await make_contact_with_contract_link(
        test_engine, org=org, prop=weg, contact_impower_id=7100001, contract_type=ContractType.OWNER
    )
    tenant, _ = await make_contact_with_contract_link(
        test_engine, org=org, prop=mv, contact_impower_id=7100002, contract_type=ContractType.TENANT
    )
    # Same person number on a second object → one entry, "+1".
    await make_contact_with_contract_link(
        test_engine, org=org, prop=mv, contact_impower_id=7100003, contract_type=ContractType.TENANT
    )
    ended, _ = await make_contact_with_contract_link(
        test_engine,
        org=org,
        prop=weg,
        contact_impower_id=7100004,
        contract_type=ContractType.OWNER,
        end_date=date.today() - timedelta(days=30),
    )
    no_phone, _ = await make_contact_with_contract_link(
        test_engine, org=org, prop=weg, contact_impower_id=7100005
    )
    await _set_phone(test_engine, owner.id, "0711 987 65 43")
    await _set_phone(test_engine, tenant.id, "+49 176 1112223")
    await _set_phone(test_engine, ended.id, "0711 1111111")  # contract ended → not listed
    assert no_phone.phone is None

    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    _, o_email, o_pw = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=7100001
    )
    v_token, o_token = _login(v_email, v_pw), _login(o_email, o_pw)
    with TestClient(app) as client:
        r = client.get("/me/call-directory", headers={"Authorization": f"Bearer {v_token}"})
        assert r.status_code == 200, r.text
        body = r.json()
        numbers = [e["number"] for e in body["entries"]]
        assert numbers == sorted(numbers)
        by_number = {e["number"]: e["label"] for e in body["entries"]}
        assert (owner.last_name or "") in by_number[497119876543]
        assert "WEG Hasenbergstr. 32" in by_number[497119876543]
        assert len(by_number[497119876543]) <= 60
        assert "MV Karlstr. 5 (Mieter)" in by_number[491761112223]
        assert 49711111111 not in by_number  # ended contract
        assert body["contacts"] == 2

        # Owners never get the org-wide phone book.
        assert (
            client.get(
                "/me/call-directory", headers={"Authorization": f"Bearer {o_token}"}
            ).status_code
            == 403
        )
