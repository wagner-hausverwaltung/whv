"""Ticket message attachments (Item 7).

Covers the per-message upload + authenticated download endpoints
(/me and /admin variants), the `attachments` field on
TicketDetailResponse, cross-org scope isolation, and the
deferred-notification flow (POST .../notify) that sends an outbound
email with files actually attached.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import get_settings
from app.integrations.email.client import get_email_client
from app.main import app
from app.models import UserRole
from app.tests._factories import make_org, make_user


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
    ) -> str:
        msg_id = f"sim-{uuid.uuid4()}"
        self.sent.append(
            {
                "to": to,
                "subject": subject,
                "attachments": attachments or [],
                "id": msg_id,
            }
        )
        return msg_id


@pytest_asyncio.fixture
async def stub_email() -> AsyncIterator[_StubEmailClient]:
    stub = _StubEmailClient()

    async def _override() -> AsyncIterator[_StubEmailClient]:
        yield stub

    app.dependency_overrides[get_email_client] = _override
    yield stub
    app.dependency_overrides.pop(get_email_client, None)


@pytest_asyncio.fixture
async def tmp_attachment_dir(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[str]:
    """Same pattern as test_documents.py — env var + lru_cache flip so
    the storage helper writes to a tmpdir instead of /var/lib/whv."""
    tmp_dir = tmp_path_factory.mktemp("whv-attachments")
    monkeypatch.setenv("TICKET_ATTACHMENT_DIR", str(tmp_dir))
    get_settings.cache_clear()
    try:
        yield str(tmp_dir)
    finally:
        get_settings.cache_clear()


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    token: str = r.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_ticket(client: TestClient, token: str) -> tuple[str, str]:
    """Returns (ticket_id, first_message_id)."""
    r = client.post(
        "/me/tickets",
        headers=_auth(token),
        json={
            "subject": "Mit Anhang",
            "body": "Bitte Foto anschauen.",
            "category": "SCHADEN_ALLGEMEIN",
        },
    )
    r.raise_for_status()
    body = r.json()
    return body["id"], body["messages"][0]["id"]


# --- Upload + download roundtrip ---------------------------------------------


async def test_owner_can_upload_and_download_own_attachment(
    test_engine: AsyncEngine,
    stub_email: _StubEmailClient,
    tmp_attachment_dir: str,
) -> None:
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)  # so notify has a recipient
    _, e_email, e_pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    token = _login(e_email, e_pw)

    photo_bytes = b"\x89PNG\r\n\x1a\n fake png body"
    with TestClient(app) as client:
        ticket_id, msg_id = await _create_ticket(client, token)

        r_up = client.post(
            f"/me/tickets/{ticket_id}/messages/{msg_id}/attachments",
            headers=_auth(token),
            files={"file": ("foto.png", photo_bytes, "image/png")},
        )
        assert r_up.status_code == 201, r_up.text
        att = r_up.json()
        assert att["filename"] == "foto.png"
        assert att["size_bytes"] == len(photo_bytes)
        att_id = att["id"]

        r_down = client.get(
            f"/me/tickets/{ticket_id}/attachments/{att_id}/file",
            headers=_auth(token),
        )
        assert r_down.status_code == 200
        assert r_down.content == photo_bytes


async def test_attachment_appears_on_ticket_detail(
    test_engine: AsyncEngine,
    stub_email: _StubEmailClient,
    tmp_attachment_dir: str,
) -> None:
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    _, e_email, e_pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    token = _login(e_email, e_pw)

    with TestClient(app) as client:
        ticket_id, msg_id = await _create_ticket(client, token)
        client.post(
            f"/me/tickets/{ticket_id}/messages/{msg_id}/attachments",
            headers=_auth(token),
            files={"file": ("invoice.pdf", b"%PDF-1.4 fake %EOF", "application/pdf")},
        )

        r = client.get(f"/me/tickets/{ticket_id}", headers=_auth(token))
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert len(msgs) == 1
    # The eager-loaded attachments list rides along with the message.
    atts = msgs[0].get("attachments", [])
    assert len(atts) == 1
    assert atts[0]["filename"] == "invoice.pdf"


# --- Scope isolation ---------------------------------------------------------


async def test_cross_org_user_cannot_download_attachment(
    test_engine: AsyncEngine,
    stub_email: _StubEmailClient,
    tmp_attachment_dir: str,
) -> None:
    org_a = await make_org(test_engine)
    org_b = await make_org(test_engine)
    await make_user(test_engine, org=org_a, role=UserRole.VERWALTER)
    _, a_email, a_pw = await make_user(test_engine, org=org_a, role=UserRole.EIGENTUEMER)
    _, b_email, b_pw = await make_user(test_engine, org=org_b, role=UserRole.EIGENTUEMER)
    token_a = _login(a_email, a_pw)
    token_b = _login(b_email, b_pw)

    with TestClient(app) as client:
        ticket_id, msg_id = await _create_ticket(client, token_a)
        up = client.post(
            f"/me/tickets/{ticket_id}/messages/{msg_id}/attachments",
            headers=_auth(token_a),
            files={"file": ("private.pdf", b"%PDF private %EOF", "application/pdf")},
        )
        att_id = up.json()["id"]

        r = client.get(
            f"/me/tickets/{ticket_id}/attachments/{att_id}/file",
            headers=_auth(token_b),
        )
    assert r.status_code == 404  # 404 not 403 — we never leak existence


# --- File-type guard --------------------------------------------------------


async def test_upload_rejects_unsupported_extension(
    test_engine: AsyncEngine,
    stub_email: _StubEmailClient,
    tmp_attachment_dir: str,
) -> None:
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    _, e_email, e_pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    token = _login(e_email, e_pw)

    with TestClient(app) as client:
        ticket_id, msg_id = await _create_ticket(client, token)
        r = client.post(
            f"/me/tickets/{ticket_id}/messages/{msg_id}/attachments",
            headers=_auth(token),
            files={"file": ("malware.scr", b"MZ\x00", "application/octet-stream")},
        )
    assert r.status_code == 400
    assert "scr" in r.json()["detail"].lower()


# --- Deferred-notification flow ---------------------------------------------


async def test_notify_endpoint_sends_email_with_attachments(
    test_engine: AsyncEngine,
    stub_email: _StubEmailClient,
    tmp_attachment_dir: str,
) -> None:
    """The SPA's flow when files are queued: post message with
    defer_notification=True → upload files → POST .../notify. The
    notify call should fan out the email AND carry the files as
    Resend attachments. We assert on the stub's recorded payload."""
    org = await make_org(test_engine)
    # Two Verwalter so the recipient list isn't trivially empty.
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    _, e_email, e_pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    token = _login(e_email, e_pw)

    with TestClient(app) as client:
        ticket_id, _ = await _create_ticket(client, token)
        # Initial create already sent one notify (with no attachments).
        baseline = len(stub_email.sent)

        # Now post a reply with defer_notification=True.
        r_msg = client.post(
            f"/me/tickets/{ticket_id}/messages",
            headers=_auth(token),
            json={
                "body": "Hier das Bild",
                "is_internal_note": False,
                "defer_notification": True,
            },
        )
        new_msg_id = r_msg.json()["id"]
        # Deferred — no new email yet.
        assert len(stub_email.sent) == baseline

        client.post(
            f"/me/tickets/{ticket_id}/messages/{new_msg_id}/attachments",
            headers=_auth(token),
            files={"file": ("photo.jpg", b"\xff\xd8 fake jpg", "image/jpeg")},
        )

        r_notify = client.post(
            f"/me/tickets/{ticket_id}/messages/{new_msg_id}/notify",
            headers=_auth(token),
        )

    assert r_notify.status_code == 204
    # Exactly one new email since the deferred post.
    assert len(stub_email.sent) == baseline + 1
    new = stub_email.sent[-1]
    # Verwalter recipients (the two we created) — author excluded.
    assert isinstance(new["to"], list)
    assert all(addr != e_email for addr in new["to"])
    # Attachment forwarded through to Resend.
    assert len(new["attachments"]) == 1
    assert new["attachments"][0]["filename"] == "photo.jpg"
    # Resend expects base64-encoded content.
    assert isinstance(new["attachments"][0]["content"], str)
    assert len(new["attachments"][0]["content"]) > 0
