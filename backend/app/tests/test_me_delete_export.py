import json

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.main import app
from app.models import AuditLog, User, UserRole
from app.models import Session as DbSession
from app.tests._factories import make_user


def _login(email: str, password: str) -> dict[str, str]:
    with TestClient(app) as client:
        response = client.post("/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    return dict(response.json())


async def test_delete_me_soft_deletes_and_revokes(test_engine: AsyncEngine) -> None:
    user, email, password = await make_user(test_engine, role=UserRole.VERWALTER)
    tokens = _login(email, password)
    token = tokens["access_token"]

    with TestClient(app) as client:
        response = client.delete("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 204

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        fresh = await s.get(User, user.id)
        assert fresh is not None
        assert fresh.deleted_at is not None

        # All sessions for this user revoked
        sessions = (await s.scalars(select(DbSession).where(DbSession.user_id == user.id))).all()
        assert len(sessions) >= 1
        assert all(sess.revoked_at is not None for sess in sessions)

        # Audit row written
        audits = (
            await s.scalars(
                select(AuditLog)
                .where(AuditLog.actor_user_id == user.id)
                .where(AuditLog.action == "user_self_delete")
            )
        ).all()
        assert len(audits) == 1


async def test_delete_me_invalidates_subsequent_requests(test_engine: AsyncEngine) -> None:
    _, email, password = await make_user(test_engine, role=UserRole.VERWALTER)
    tokens = _login(email, password)
    token = tokens["access_token"]
    refresh = tokens["refresh_token"]

    with TestClient(app) as client:
        client.delete("/me", headers={"Authorization": f"Bearer {token}"})

        # Access token instantly invalid (auth dep rejects deleted_at != null)
        get_me = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert get_me.status_code == 401

        # Refresh token rejected (session was revoked)
        refresh_resp = client.post("/auth/refresh", json={"refresh_token": refresh})
        assert refresh_resp.status_code == 401

        # Login with same email + password rejected (user deleted)
        login_resp = client.post("/auth/login", json={"email": email, "password": password})
        assert login_resp.status_code == 401


async def test_export_returns_user_data_without_secrets(test_engine: AsyncEngine) -> None:
    user, email, password = await make_user(test_engine, role=UserRole.VERWALTER)
    tokens = _login(email, password)
    token = tokens["access_token"]

    with TestClient(app) as client:
        response = client.get("/me/export", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    disposition = response.headers.get("content-disposition", "")
    assert "attachment" in disposition
    assert f"whv-export-{user.id}" in disposition

    body = response.json()
    assert body["format_version"] == "1.0"
    assert body["user"]["id"] == str(user.id)
    assert body["user"]["email"] == email
    assert body["user"]["role"] == "verwalter"

    # Sessions present, no token-hash secret
    assert len(body["sessions"]) >= 1
    for s in body["sessions"]:
        assert "refresh_token_hash" not in s
        assert "id" in s and "expires_at" in s

    # Audit list always present (may be empty for a fresh user)
    assert isinstance(body["audit_log_entries"], list)

    # No secrets anywhere in the dumped JSON
    raw = json.dumps(body)
    for forbidden in ("password_hash", "mfa_secret", "refresh_token_hash"):
        assert forbidden not in raw, f"{forbidden} leaked in export body"


async def test_export_requires_auth(test_engine: AsyncEngine) -> None:
    with TestClient(app) as client:
        response = client.get("/me/export")
    assert response.status_code == 401


async def test_delete_me_requires_auth(test_engine: AsyncEngine) -> None:
    with TestClient(app) as client:
        response = client.delete("/me")
    assert response.status_code == 401
