"""Tests for the admin-UI forgot/reset password flow at /admin-ui/forgot-password
and /admin-ui/reset-password.

These wrap the existing JSON /auth/forgot-password and /auth/reset-password
handlers. We test the HTML-specific behaviour: form renders, no-enumeration
flash, token-in-URL flow, redirect to login on success, login with new pw works.
"""

import secrets
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.api.v1.auth import _hash_reset_token
from app.auth.dependencies import ADMIN_COOKIE_NAME
from app.integrations.email.client import EmailError, get_email_client
from app.main import app
from app.models import PasswordResetToken, UserRole
from app.tests._factories import make_user


class _StubEmailClient:
    def __init__(self, *, raise_error: bool = False) -> None:
        self.sent: list[dict[str, str]] = []
        self.raise_error = raise_error

    async def send(self, *, to: str, subject: str, html: str, text: str) -> str:
        if self.raise_error:
            raise EmailError("simulated failure")
        msg_id = f"sim-{uuid.uuid4()}"
        self.sent.append({"to": to, "subject": subject, "html": html, "text": text})
        return msg_id


@pytest_asyncio.fixture
async def stub_email() -> AsyncIterator[_StubEmailClient]:
    stub = _StubEmailClient()

    async def _override() -> AsyncIterator[_StubEmailClient]:
        yield stub

    app.dependency_overrides[get_email_client] = _override
    yield stub
    app.dependency_overrides.pop(get_email_client, None)


# --- Forgot-password page -----------------------------------------------------


def test_forgot_password_form_renders() -> None:
    with TestClient(app) as client:
        r = client.get("/admin-ui/forgot-password")
    assert r.status_code == 200
    assert "Passwort vergessen" in r.text
    assert "E-Mail-Adresse" in r.text


def test_forgot_password_link_on_login_page() -> None:
    with TestClient(app) as client:
        r = client.get("/admin-ui/login")
    assert r.status_code == 200
    assert 'href="/admin-ui/forgot-password"' in r.text
    assert "Passwort vergessen" in r.text


async def test_forgot_password_known_email_sends_link_with_admin_url(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    user, email, _password = await make_user(test_engine, role=UserRole.VERWALTER)
    with TestClient(app) as client:
        r = client.post(
            "/admin-ui/forgot-password",
            data={"email": email},
            follow_redirects=False,
        )
    # Always renders the "submitted" page inline (no redirect) so the no-enum
    # behaviour is identical whether or not the email matched.
    assert r.status_code == 200
    # template wraps across newlines, so split on whitespace and check both ends
    body_normalized = " ".join(r.text.split())
    assert "wurde ein Link zum Zurücksetzen versandt" in body_normalized

    # Email was sent and contains a clickable admin-UI reset URL (built from
    # ADMIN_UI_BASE_URL setting — defaults to http://localhost:8000 in tests)
    assert len(stub_email.sent) == 1
    msg = stub_email.sent[0]
    assert msg["to"] == email
    assert "/admin-ui/reset-password?token=" in msg["text"]
    assert "/admin-ui/reset-password?token=" in msg["html"]

    # Token row exists
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        tokens = (
            await s.scalars(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
        ).all()
        assert len(tokens) >= 1


async def test_forgot_password_unknown_email_still_renders_submitted_page(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    unknown_email = f"nobody-{uuid.uuid4().hex[:8]}@test.de"
    with TestClient(app) as client:
        r = client.post(
            "/admin-ui/forgot-password",
            data={"email": unknown_email},
            follow_redirects=False,
        )
    assert r.status_code == 200
    # template wraps across newlines, so split on whitespace and check both ends
    body_normalized = " ".join(r.text.split())
    assert "wurde ein Link zum Zurücksetzen versandt" in body_normalized
    # No email sent for unknown user
    assert stub_email.sent == []


# --- Reset-password page ------------------------------------------------------


def test_reset_password_form_without_token_is_400() -> None:
    with TestClient(app) as client:
        r = client.get("/admin-ui/reset-password")
    assert r.status_code == 400
    # The template's no-token branch shows a friendly "use the link from the
    # email" message + a link to request a new one (rather than echoing back
    # the technical error key).
    assert "Reset-E-Mail" in r.text
    assert 'href="/admin-ui/forgot-password"' in r.text


def test_reset_password_form_with_token_renders_hidden_field() -> None:
    with TestClient(app) as client:
        r = client.get("/admin-ui/reset-password?token=PRETEND_TOKEN_XYZ")
    assert r.status_code == 200
    assert 'name="token"' in r.text
    assert 'value="PRETEND_TOKEN_XYZ"' in r.text
    assert 'name="password"' in r.text


async def test_reset_password_happy_path_redirects_to_login_and_pw_updated(
    test_engine: AsyncEngine,
) -> None:
    user, email, old_pw = await make_user(test_engine, role=UserRole.VERWALTER)

    raw_token = secrets.token_urlsafe(32)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        s.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=_hash_reset_token(raw_token),
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
            )
        )
        await s.commit()

    new_pw = "fresh-strong-pw-678"
    with TestClient(app) as client:
        r = client.post(
            "/admin-ui/reset-password",
            data={"token": raw_token, "password": new_pw},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert r.headers["location"] == "/admin-ui/login?reset=ok"

        # The login page now shows the reset-ok flash
        login = client.get("/admin-ui/login?reset=ok")
        assert "Passwort wurde aktualisiert" in login.text

        # Old pw rejected, new pw works
        bad = client.post(
            "/admin-ui/login",
            data={"email": email, "password": old_pw},
            follow_redirects=False,
        )
        assert bad.status_code == 401

        good = client.post(
            "/admin-ui/login",
            data={"email": email, "password": new_pw},
            follow_redirects=False,
        )
        assert good.status_code == 303
        assert ADMIN_COOKIE_NAME in client.cookies


async def test_reset_password_expired_token_re_renders_form_with_error(
    test_engine: AsyncEngine,
) -> None:
    user, _email, _pw = await make_user(test_engine, role=UserRole.VERWALTER)
    raw_token = secrets.token_urlsafe(32)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        s.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=_hash_reset_token(raw_token),
                expires_at=datetime.now(UTC) - timedelta(minutes=1),  # expired
            )
        )
        await s.commit()

    with TestClient(app) as client:
        r = client.post(
            "/admin-ui/reset-password",
            data={"token": raw_token, "password": "another-strong-pw"},
            follow_redirects=False,
        )
    assert r.status_code == 400
    assert "Token ungültig" in r.text
    # The form should still be rendered with the token, so the user can request a new one
    assert 'href="/admin-ui/forgot-password"' not in r.text  # plain reset page, not 404
    assert "Neues Passwort setzen" in r.text


def test_reset_password_bogus_token_re_renders_form_with_error() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/admin-ui/reset-password",
            data={"token": "not-a-real-token", "password": "another-strong-pw"},
            follow_redirects=False,
        )
    assert r.status_code == 400
    assert "Token ungültig" in r.text


# --- Email template ----------------------------------------------------------


def test_password_reset_email_includes_reset_url_button() -> None:
    """The render function must surface the reset URL in both bodies."""
    from app.integrations.email.password_reset import render_password_reset_email

    subject, html, text = render_password_reset_email(
        email="user@test.de",
        token="ABCDEFGHIJK",
        ttl_minutes=30,
        reset_url="https://admin.example.com/admin-ui/reset-password?token=ABCDEFGHIJK",
    )
    assert "Passwort zurücksetzen" in subject
    # HTML body has a clickable anchor + the URL repeated as text
    assert 'href="https://admin.example.com/admin-ui/reset-password?token=ABCDEFGHIJK"' in html
    assert "Neues Passwort setzen" in html
    # Text body has the URL
    assert "https://admin.example.com/admin-ui/reset-password?token=ABCDEFGHIJK" in text
    # Token still appears as fallback for CLI / curl users
    assert "ABCDEFGHIJK" in text
    assert "ABCDEFGHIJK" in html
