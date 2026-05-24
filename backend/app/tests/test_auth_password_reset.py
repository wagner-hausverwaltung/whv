import secrets
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.api.v1.auth import _hash_reset_token
from app.integrations.email.client import EmailError, get_email_client
from app.main import app
from app.models import AuditLog, PasswordResetToken, UserRole
from app.models import Session as DbSession
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


def _login(email: str, password: str) -> dict[str, str]:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return dict(r.json())


async def test_forgot_password_known_email_creates_token_and_sends_email(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    user, email, _password = await make_user(test_engine, role=UserRole.VERWALTER)

    with TestClient(app) as client:
        r = client.post("/auth/forgot-password", json={"email": email})
    assert r.status_code == 204

    assert len(stub_email.sent) == 1
    assert stub_email.sent[0]["to"] == email
    # Token must be present in the email body (German template uses both HTML + text)
    raw_token_candidates = [
        line for line in stub_email.sent[0]["text"].splitlines() if "Token:" in line
    ]
    assert raw_token_candidates  # the template includes a Token: line

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        tokens = (
            await s.scalars(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
        ).all()
        assert len(tokens) >= 1


async def test_forgot_password_unknown_email_returns_204_and_sends_nothing(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    unknown_email = f"nobody-{uuid.uuid4().hex[:8]}@test.de"
    with TestClient(app) as client:
        r = client.post("/auth/forgot-password", json={"email": unknown_email})
    assert r.status_code == 204
    assert stub_email.sent == []


async def test_reset_password_happy_path_updates_pw_and_revokes_sessions(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    user, email, old_pw = await make_user(test_engine, role=UserRole.VERWALTER)

    # Create a session by logging in (so we can verify it gets revoked)
    _ = _login(email, old_pw)

    # Insert a token directly (skip going through forgot-password)
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

    new_pw = "brand-new-pw-12345"
    with TestClient(app) as client:
        r = client.post(
            "/auth/reset-password",
            json={"token": raw_token, "new_password": new_pw},
        )
    assert r.status_code == 204

    async with sm() as s:
        # Token consumed
        consumed = await s.scalar(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
        )
        assert consumed is not None
        assert consumed.consumed_at is not None
        # Sessions revoked
        sessions = (await s.scalars(select(DbSession).where(DbSession.user_id == user.id))).all()
        assert all(sess.revoked_at is not None for sess in sessions)
        # Audit row written
        audit = await s.scalar(
            select(AuditLog).where(
                AuditLog.actor_user_id == user.id,
                AuditLog.action == "user_password_reset",
            )
        )
        assert audit is not None

    # Old password rejected
    with TestClient(app) as client:
        old = client.post("/auth/login", json={"email": email, "password": old_pw})
        assert old.status_code == 401
        # New password works
        new = client.post("/auth/login", json={"email": email, "password": new_pw})
        assert new.status_code == 200


async def test_reset_password_expired_token_rejected(test_engine: AsyncEngine) -> None:
    user, _email, _pw = await make_user(test_engine, role=UserRole.VERWALTER)
    raw_token = secrets.token_urlsafe(32)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        s.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=_hash_reset_token(raw_token),
                expires_at=datetime.now(UTC) - timedelta(minutes=1),  # already expired
            )
        )
        await s.commit()

    with TestClient(app) as client:
        r = client.post(
            "/auth/reset-password",
            json={"token": raw_token, "new_password": "another-strong-pw"},
        )
    assert r.status_code == 400


async def test_reset_password_consumed_token_rejected(test_engine: AsyncEngine) -> None:
    user, _email, _pw = await make_user(test_engine, role=UserRole.VERWALTER)
    raw_token = secrets.token_urlsafe(32)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        s.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=_hash_reset_token(raw_token),
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
                consumed_at=datetime.now(UTC),  # already used
            )
        )
        await s.commit()

    with TestClient(app) as client:
        r = client.post(
            "/auth/reset-password",
            json={"token": raw_token, "new_password": "another-strong-pw"},
        )
    assert r.status_code == 400


async def test_reset_password_bogus_token_rejected(test_engine: AsyncEngine) -> None:
    with TestClient(app) as client:
        r = client.post(
            "/auth/reset-password",
            json={"token": "not-a-real-token", "new_password": "another-strong-pw"},
        )
    assert r.status_code == 400


async def test_forgot_password_email_failure_does_not_break_response(
    test_engine: AsyncEngine,
) -> None:
    """If Resend is down, /auth/forgot-password still 204s and the token is created.

    User can request another reset; they just don't get the email this time.
    """
    failing = _StubEmailClient(raise_error=True)

    async def _override() -> AsyncIterator[_StubEmailClient]:
        yield failing

    app.dependency_overrides[get_email_client] = _override
    try:
        user, email, _pw = await make_user(test_engine, role=UserRole.VERWALTER)
        with TestClient(app) as client:
            r = client.post("/auth/forgot-password", json={"email": email})
        assert r.status_code == 204
        sm = async_sessionmaker(test_engine, expire_on_commit=False)
        async with sm() as s:
            tokens = (
                await s.scalars(
                    select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
                )
            ).all()
            assert len(tokens) >= 1
    finally:
        app.dependency_overrides.pop(get_email_client, None)
