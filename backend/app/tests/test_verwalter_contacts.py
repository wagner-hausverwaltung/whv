"""Siri helpers: contact search + e-mail message to a contact (Verwalter-only)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.integrations.email.client import get_email_client
from app.main import app
from app.models import Contact, UserRole
from app.models.contract import ContractType
from app.tests._factories import make_contact_with_contract_link, make_org, make_property, make_user


class _StubEmailClient:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(
        self,
        *,
        to: str | list[str],
        subject: str,
        html: str,
        text: str,
        headers: dict[str, str] | None = None,
        reply_to: str | None = None,
        attachments: list[dict[str, str]] | None = None,
        from_address: str | None = None,
        from_name: str | None = None,
    ) -> str:
        self.sent.append({"to": to, "subject": subject, "text": text, "reply_to": reply_to})
        return f"sim-{uuid.uuid4()}"


@pytest_asyncio.fixture
async def stub_email() -> AsyncIterator[_StubEmailClient]:
    stub = _StubEmailClient()

    async def _override() -> AsyncIterator[_StubEmailClient]:
        yield stub

    app.dependency_overrides[get_email_client] = _override
    yield stub
    app.dependency_overrides.pop(get_email_client, None)


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    token: str = r.json()["access_token"]
    return token


async def test_search_and_message_contact(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    org = await make_org(test_engine)
    weg = await make_property(test_engine, org=org, name="WEG Hasenbergstraße 32, 70176 Stuttgart")
    contact, _ = await make_contact_with_contract_link(
        test_engine, org=org, prop=weg, contact_impower_id=7300001, contract_type=ContractType.OWNER
    )
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        await s.execute(
            update(Contact)
            .where(Contact.id == contact.id)
            .values(first_name="Franziska", last_name="Fritz", email="franziska@example.de")
        )
        await s.commit()
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    _, o_email, o_pw = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=7300001
    )
    v_token, o_token = _login(v_email, v_pw), _login(o_email, o_pw)
    with TestClient(app) as client:
        h = {"Authorization": f"Bearer {v_token}"}
        found = client.get("/me/contacts/search", headers=h, params={"q": "fritz"}).json()
        assert [c["name"] for c in found] == ["Franziska Fritz"]
        assert found[0]["role"] == "Eigentümer"
        assert found[0]["property_name"].startswith("WEG Hasenbergstraße")
        cid = found[0]["id"]

        r = client.post(
            f"/me/contacts/{cid}/message",
            headers=h,
            json={"text": "Der Handwerker kommt morgen um 9 Uhr."},
        )
        assert r.status_code == 200, r.text
        assert r.json()["sent"] is True
        assert r.json()["to"] == "franziska@example.de"
        mail = stub_email.sent[-1]
        assert mail["to"] == "franziska@example.de"
        assert "Handwerker kommt morgen" in mail["text"]
        assert mail["reply_to"] == v_email

        # Owners may neither search nor send.
        oh = {"Authorization": f"Bearer {o_token}"}
        assert client.get("/me/contacts/search", headers=oh).status_code == 403
        assert (
            client.post(
                f"/me/contacts/{cid}/message", headers=oh, json={"text": "hallo"}
            ).status_code
            == 403
        )
