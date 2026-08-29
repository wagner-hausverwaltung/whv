"""Release gate for Abrechnungs-Dokumente (B42-Vorfall, 2026-08-29).

Impower exports Hausgeldabrechnung PDFs the moment they are generated —
draft or not, with state=READY and no marker (verified against the live
API). So JAHRESABRECHNUNG/WIRTSCHAFTSPLAN documents stay invisible to
owners and never notify until the Verwalter releases them.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.main import app
from app.models import Document, DocumentKind, UserRole
from app.services.document_notify import notify_new_documents
from app.tests._factories import (
    make_contact_with_contract_link,
    make_document,
    make_org,
    make_property,
    make_user,
)
from app.tests.test_trips import _auth, _login


class _RecordingEmail:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, *, to: str, subject: str, html: str, text: str, **kwargs: Any) -> str:
        self.sent.append(to)
        return "rec-id"


def _uid() -> int:
    import uuid

    return uuid.uuid4().int % 9_000_000_000_000_000


async def test_withheld_abrechnung_is_invisible_to_owners_until_release(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    c_owner = _uid()
    _, owner_email, owner_pw = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c_owner
    )
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=c_owner
    )
    withheld = await make_document(
        test_engine, org=org, prop=prop, kind=DocumentKind.JAHRESABRECHNUNG, released=False
    )
    visible = await make_document(
        test_engine, org=org, prop=prop, kind=DocumentKind.JAHRESABRECHNUNG, released=True
    )
    # Other kinds are never gated — a fresh invoice stays visible.
    invoice = await make_document(
        test_engine, org=org, prop=prop, kind=DocumentKind.SONSTIGES, released=False
    )

    _, vw_email, vw_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    owner_token = _login(owner_email, owner_pw)
    vw_token = _login(vw_email, vw_pw)
    with TestClient(app) as client:
        r = client.get(f"/me/properties/{prop.id}/documents", headers=_auth(owner_token))
        assert r.status_code == 200, r.text
        ids = {d["id"] for d in json.loads(r.text)}
        assert str(withheld.id) not in ids
        assert str(visible.id) in ids
        assert str(invoice.id) in ids

        # the Verwalter releases it via the admin endpoint …
        r = client.get("/admin/documents/withheld", headers=_auth(vw_token))
        assert r.status_code == 200
        assert str(withheld.id) in {d["id"] for d in r.json()}
        r = client.post(
            "/admin/documents/release",
            headers=_auth(vw_token),
            json={"document_ids": [str(withheld.id)]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["released"] == 1

        # … and the owner can see it now.
        r = client.get(f"/me/properties/{prop.id}/documents", headers=_auth(owner_token))
        assert str(withheld.id) in {d["id"] for d in json.loads(r.text)}


async def test_withheld_abrechnung_does_not_notify_release_does(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    c_owner = _uid()
    _, owner_email, _ = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c_owner
    )
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=c_owner
    )
    doc = await make_document(
        test_engine, org=org, prop=prop, kind=DocumentKind.JAHRESABRECHNUNG, released=False
    )
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    recorder = _RecordingEmail()
    async with sm() as s:
        await notify_new_documents(s, email_client=recorder)
    # the withheld statement must not have mailed the owner …
    assert owner_email not in recorder.sent
    async with sm() as s:
        row = await s.get(Document, doc.id)
        assert row is not None and row.notified_at is None

    # … until it is released.
    from datetime import UTC, datetime

    async with sm() as s:
        row = await s.get(Document, doc.id)
        assert row is not None
        row.released_at = datetime.now(UTC)
        await s.commit()
    recorder2 = _RecordingEmail()
    async with sm() as s:
        await notify_new_documents(s, email_client=recorder2)
    assert owner_email in recorder2.sent
