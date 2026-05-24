"""Tests for the Jinja admin UI mounted at /admin-ui.

Covers: login/logout (cookie session), role gate (VERWALTER only),
unauthenticated redirect, dashboard counts, invite create/revoke/filter,
audit log render.
"""

import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.auth.dependencies import ADMIN_COOKIE_NAME
from app.integrations.email.client import EmailError, get_email_client
from app.main import app
from app.models import AuditLog, InviteCode, UserRole
from app.tests._factories import make_user


class _StubEmailClient:
    def __init__(self, *, raise_error: bool = False) -> None:
        self.sent: list[dict[str, str]] = []
        self.raise_error = raise_error

    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str,
        headers: dict[str, str] | None = None,
    ) -> str:
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


def _login_via_ui(client: TestClient, email: str, password: str) -> None:
    """POSTs /admin-ui/login on the given client; raises if cookie isn't set.

    The client retains the cookie for subsequent requests on the same instance.
    """
    r = client.post(
        "/admin-ui/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert r.status_code == 303, f"expected 303, got {r.status_code}: {r.text[:200]}"
    assert r.headers["location"] == "/admin-ui/"
    assert ADMIN_COOKIE_NAME in client.cookies


# --- Login / role gate / redirect ---------------------------------------------


def test_login_form_renders() -> None:
    with TestClient(app) as client:
        r = client.get("/admin-ui/login")
    assert r.status_code == 200
    assert "Anmelden" in r.text or "E-Mail" in r.text  # german form


async def test_login_with_bad_password_returns_401(test_engine: AsyncEngine) -> None:
    _, email, _ = await make_user(test_engine, role=UserRole.VERWALTER)
    with TestClient(app) as client:
        r = client.post(
            "/admin-ui/login",
            data={"email": email, "password": "wrong-password"},
            follow_redirects=False,
        )
    assert r.status_code == 401
    assert ADMIN_COOKIE_NAME not in r.cookies


async def test_login_with_non_verwalter_rejected(test_engine: AsyncEngine) -> None:
    _, email, password = await make_user(test_engine, role=UserRole.EIGENTUEMER)
    with TestClient(app) as client:
        r = client.post(
            "/admin-ui/login",
            data={"email": email, "password": password},
            follow_redirects=False,
        )
    assert r.status_code == 401
    assert ADMIN_COOKIE_NAME not in r.cookies


async def test_login_with_verwalter_sets_cookie_and_redirects(test_engine: AsyncEngine) -> None:
    _, email, password = await make_user(test_engine, role=UserRole.VERWALTER)
    with TestClient(app) as client:
        _login_via_ui(client, email, password)
        # Cookie now allows dashboard access
        r = client.get("/admin-ui/", follow_redirects=False)
        assert r.status_code == 200


def test_dashboard_without_cookie_redirects_to_login() -> None:
    with TestClient(app) as client:
        r = client.get("/admin-ui/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin-ui/login"


def test_dashboard_with_bogus_cookie_redirects_to_login() -> None:
    with TestClient(app) as client:
        client.cookies.set(ADMIN_COOKIE_NAME, "not-a-real-jwt")
        r = client.get("/admin-ui/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin-ui/login"


async def test_logout_clears_cookie(test_engine: AsyncEngine) -> None:
    _, email, password = await make_user(test_engine, role=UserRole.VERWALTER)
    with TestClient(app) as client:
        _login_via_ui(client, email, password)
        r = client.post("/admin-ui/logout", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/admin-ui/login"
        # Subsequent dashboard fetch must redirect again
        r2 = client.get("/admin-ui/", follow_redirects=False)
        assert r2.status_code == 303


# --- Dashboard counts ---------------------------------------------------------


async def test_dashboard_renders_counts(test_engine: AsyncEngine) -> None:
    _, email, password = await make_user(test_engine, role=UserRole.VERWALTER)
    with TestClient(app) as client:
        _login_via_ui(client, email, password)
        r = client.get("/admin-ui/")
    assert r.status_code == 200
    assert "Dashboard" in r.text or "Übersicht" in r.text
    # Just ensure the german stat labels render — actual numbers depend on shared DB state
    assert "Offene" in r.text or "Einladungen" in r.text


# --- Invites ------------------------------------------------------------------


async def test_invites_list_renders(test_engine: AsyncEngine) -> None:
    _, email, password = await make_user(test_engine, role=UserRole.VERWALTER)
    with TestClient(app) as client:
        _login_via_ui(client, email, password)
        r = client.get("/admin-ui/invites")
    assert r.status_code == 200
    assert "Einladungen" in r.text


async def test_invites_new_form_renders(test_engine: AsyncEngine) -> None:
    _, email, password = await make_user(test_engine, role=UserRole.VERWALTER)
    with TestClient(app) as client:
        _login_via_ui(client, email, password)
        r = client.get("/admin-ui/invites/new")
    assert r.status_code == 200
    assert "Neue Einladung" in r.text
    assert "verwalter" in r.text or "eigentuemer" in r.text


async def test_invite_create_via_ui_persists_and_sends_email(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    user, email, password = await make_user(test_engine, role=UserRole.VERWALTER)
    new_email = f"ui-{uuid.uuid4().hex[:8]}@test.de"
    with TestClient(app) as client:
        _login_via_ui(client, email, password)
        r = client.post(
            "/admin-ui/invites/new",
            data={
                "email": new_email,
                "role": "eigentuemer",
                "contact_id_impower": "98765",
                "ttl_days": "7",
            },
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert "/admin-ui/invites?status=pending&created=" in r.headers["location"]

    # Email was sent + invite + audit row persisted under our org
    assert len(stub_email.sent) == 1
    assert stub_email.sent[0]["to"] == new_email

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        invite = await s.scalar(select(InviteCode).where(InviteCode.email == new_email))
        assert invite is not None
        assert invite.organization_id == user.organization_id
        assert invite.contact_id_impower == 98765
        assert invite.role == UserRole.EIGENTUEMER
        audit = await s.scalar(
            select(AuditLog).where(
                AuditLog.action == "invite_created",
                AuditLog.target_id == invite.code,
            )
        )
        assert audit is not None
        assert audit.payload_json is not None
        assert audit.payload_json["via"] == "admin_ui"
        assert audit.payload_json["email_sent"] is True


async def test_invite_create_rejects_invalid_contact_id(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    _, email, password = await make_user(test_engine, role=UserRole.VERWALTER)
    with TestClient(app) as client:
        _login_via_ui(client, email, password)
        r = client.post(
            "/admin-ui/invites/new",
            data={
                "email": "x@y.de",
                "role": "eigentuemer",
                "contact_id_impower": "not-a-number",
                "ttl_days": "7",
            },
            follow_redirects=False,
        )
    assert r.status_code == 400
    assert "Impower-Contact-ID" in r.text
    assert stub_email.sent == []


async def test_invite_revoke_via_ui_marks_consumed(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    _, email, password = await make_user(test_engine, role=UserRole.VERWALTER)
    new_email = f"revoke-{uuid.uuid4().hex[:8]}@test.de"
    with TestClient(app) as client:
        _login_via_ui(client, email, password)
        create = client.post(
            "/admin-ui/invites/new",
            data={"email": new_email, "role": "eigentuemer", "ttl_days": "7"},
            follow_redirects=False,
        )
        assert create.status_code == 303
        # extract code from redirect location
        code = create.headers["location"].split("created=")[-1]

        revoke = client.post(
            f"/admin-ui/invites/{code}/revoke",
            follow_redirects=False,
        )
        assert revoke.status_code == 303
        assert revoke.headers["location"] == "/admin-ui/invites"

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        invite = await s.scalar(select(InviteCode).where(InviteCode.code == code))
        assert invite is not None
        assert invite.consumed_at is not None
        audit = await s.scalar(
            select(AuditLog).where(
                AuditLog.action == "invite_revoked",
                AuditLog.target_id == code,
            )
        )
        assert audit is not None


async def test_invites_status_filter_only_shows_matching(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    _, email, password = await make_user(test_engine, role=UserRole.VERWALTER)
    pending_email = f"p-{uuid.uuid4().hex[:8]}@test.de"
    consumed_email = f"c-{uuid.uuid4().hex[:8]}@test.de"

    with TestClient(app) as client:
        _login_via_ui(client, email, password)
        # one pending invite
        client.post(
            "/admin-ui/invites/new",
            data={"email": pending_email, "role": "eigentuemer", "ttl_days": "7"},
            follow_redirects=False,
        )
        # one invite we then revoke (= consumed)
        r = client.post(
            "/admin-ui/invites/new",
            data={"email": consumed_email, "role": "eigentuemer", "ttl_days": "7"},
            follow_redirects=False,
        )
        consumed_code = r.headers["location"].split("created=")[-1]
        client.post(f"/admin-ui/invites/{consumed_code}/revoke", follow_redirects=False)

        pending_page = client.get("/admin-ui/invites?status_filter=pending")
        consumed_page = client.get("/admin-ui/invites?status_filter=consumed")

    assert pending_email in pending_page.text
    assert consumed_email not in pending_page.text
    assert consumed_email in consumed_page.text
    assert pending_email not in consumed_page.text


# --- Audit log ----------------------------------------------------------------


async def test_audit_log_renders_recent_rows(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    _, email, password = await make_user(test_engine, role=UserRole.VERWALTER)
    with TestClient(app) as client:
        _login_via_ui(client, email, password)
        # create an invite so we know at least one audit row exists for our org
        client.post(
            "/admin-ui/invites/new",
            data={
                "email": f"audit-{uuid.uuid4().hex[:8]}@test.de",
                "role": "eigentuemer",
                "ttl_days": "7",
            },
            follow_redirects=False,
        )
        r = client.get("/admin-ui/audit")
    assert r.status_code == 200
    assert "Audit-Log" in r.text
    assert "invite_created" in r.text
