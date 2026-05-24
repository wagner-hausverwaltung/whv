import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.integrations.email.client import EmailError, get_email_client
from app.integrations.email.invites import render_invite_email
from app.main import app
from app.models import AuditLog, InviteCode, UserRole
from app.tests._factories import make_user


class _StubEmailClient:
    """In-memory email sender for tests. Set raise_error=True to simulate provider failure."""

    def __init__(self, *, raise_error: bool = False) -> None:
        self.sent: list[dict[str, str]] = []
        self.raise_error = raise_error

    async def send(self, *, to: str, subject: str, html: str, text: str) -> str:
        if self.raise_error:
            raise EmailError("simulated provider failure")
        msg_id = f"sim-{uuid.uuid4()}"
        self.sent.append({"to": to, "subject": subject, "id": msg_id})
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
async def stub_failing_email() -> AsyncIterator[_StubEmailClient]:
    stub = _StubEmailClient(raise_error=True)

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


async def test_create_invite_requires_verwalter(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    _, email, password = await make_user(test_engine, role=UserRole.EIGENTUEMER)
    token = _login(email, password)
    with TestClient(app) as client:
        r = client.post(
            "/admin/invites",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "new@example.com", "role": "eigentuemer"},
        )
    assert r.status_code == 403
    assert stub_email.sent == []


async def test_create_invite_requires_auth(test_engine: AsyncEngine) -> None:
    with TestClient(app) as client:
        r = client.post("/admin/invites", json={"email": "x@y.de", "role": "eigentuemer"})
    assert r.status_code == 401


async def test_create_invite_happy_path(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    user, email, password = await make_user(test_engine, role=UserRole.VERWALTER)
    token = _login(email, password)
    new_email = f"new-{uuid.uuid4().hex[:8]}@test.de"

    with TestClient(app) as client:
        r = client.post(
            "/admin/invites",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email": new_email,
                "role": "eigentuemer",
                "contact_id_impower": 12345,
                "ttl_days": 14,
            },
        )

    assert r.status_code == 201
    body = r.json()
    assert body["email"] == new_email
    assert body["role"] == "eigentuemer"
    assert body["status"] == "pending"
    assert body["contact_id_impower"] == 12345
    assert body["email_message_id"] is not None
    assert body["email_message_id"].startswith("sim-")

    # The email was sent to the right address
    assert len(stub_email.sent) == 1
    assert stub_email.sent[0]["to"] == new_email
    assert "WHV-Portal" in stub_email.sent[0]["subject"]

    # Invite row + audit row exist in DB
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        invite = await s.scalar(select(InviteCode).where(InviteCode.email == new_email))
        assert invite is not None
        assert invite.created_by == user.id
        audit = await s.scalar(
            select(AuditLog).where(
                AuditLog.action == "invite_created",
                AuditLog.target_id == invite.code,
            )
        )
        assert audit is not None
        assert audit.payload_json is not None
        assert audit.payload_json["email_sent"] is True


async def test_create_invite_with_email_failure_still_creates_invite(
    test_engine: AsyncEngine, stub_failing_email: _StubEmailClient
) -> None:
    _, email, password = await make_user(test_engine, role=UserRole.VERWALTER)
    token = _login(email, password)
    new_email = f"new-{uuid.uuid4().hex[:8]}@test.de"

    with TestClient(app) as client:
        r = client.post(
            "/admin/invites",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": new_email, "role": "verwalter"},
        )
    assert r.status_code == 201
    body = r.json()
    assert body["email_message_id"] is None  # email failed but invite created

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        invite = await s.scalar(select(InviteCode).where(InviteCode.email == new_email))
        assert invite is not None  # invite row persisted despite email failure
        audit = await s.scalar(
            select(AuditLog).where(
                AuditLog.action == "invite_created",
                AuditLog.target_id == invite.code,
            )
        )
        assert audit is not None
        assert audit.payload_json is not None
        assert audit.payload_json["email_sent"] is False
        assert "email_error" in audit.payload_json


async def test_list_invites_scoped_to_org(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    _, email, password = await make_user(test_engine, role=UserRole.VERWALTER)
    token = _login(email, password)
    unique_a = f"a-{uuid.uuid4().hex[:8]}@test.de"
    unique_b = f"b-{uuid.uuid4().hex[:8]}@test.de"

    with TestClient(app) as client:
        client.post(
            "/admin/invites",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": unique_a, "role": "eigentuemer"},
        )
        client.post(
            "/admin/invites",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": unique_b, "role": "mieter"},
        )

        list_r = client.get("/admin/invites", headers={"Authorization": f"Bearer {token}"})
    assert list_r.status_code == 200
    emails = {i["email"] for i in list_r.json()}
    assert unique_a in emails
    assert unique_b in emails


async def test_revoke_invite_blocks_redemption(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    _, admin_email, admin_pw = await make_user(test_engine, role=UserRole.VERWALTER)
    token = _login(admin_email, admin_pw)
    invitee = f"victim-{uuid.uuid4().hex[:8]}@test.de"

    with TestClient(app) as client:
        create = client.post(
            "/admin/invites",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": invitee, "role": "eigentuemer"},
        )
        code = create.json()["code"]

        revoke = client.delete(
            f"/admin/invites/{code}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert revoke.status_code == 204

        # Redeeming the revoked code now fails
        redeem = client.post(
            "/auth/invite/redeem",
            json={"code": code, "email": invitee, "password": "supersecret-pw"},
        )
        assert redeem.status_code == 400

        # Revoking the same code again 404s (already consumed)
        revoke_again = client.delete(
            f"/admin/invites/{code}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert revoke_again.status_code == 404


def test_invite_email_template_renders_both_text_and_html() -> None:
    subject, html, text = render_invite_email("user@example.de", "ABCD1234", "eigentuemer")
    assert "ABCD1234" in subject
    assert "ABCD1234" in html
    assert "ABCD1234" in text
    assert "user@example.de" in html
    assert "user@example.de" in text
    assert "eigentuemer" in html
    assert "eigentuemer" in text
    # German content (sanity-check we didn't accidentally ship the English placeholder)
    assert "Einladung" in subject
    assert "Wagner Hausverwaltung" in html
    assert "Wagner Hausverwaltung" in text
