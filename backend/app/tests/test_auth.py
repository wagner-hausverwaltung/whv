from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.main import app
from app.models import InviteCode, Session, User, UserRole
from app.tests._factories import make_invite, make_user


async def test_invite_redeem_happy_path(test_engine: AsyncEngine) -> None:
    invite, _ = await make_invite(test_engine)

    with TestClient(app) as client:
        response = client.post(
            "/auth/invite/redeem",
            json={"code": invite.code, "email": invite.email, "password": "supersecret-pw"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900  # 15 minutes
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["user"]["email"] == invite.email
    assert body["user"]["role"] == invite.role.value

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        consumed = await s.scalar(select(InviteCode).where(InviteCode.code == invite.code))
        assert consumed is not None
        assert consumed.consumed_at is not None
        created_user = await s.scalar(select(User).where(User.email == invite.email))
        assert created_user is not None
        assert created_user.password_hash is not None


async def test_invite_redeem_unknown_code(test_engine: AsyncEngine) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/auth/invite/redeem",
            json={"code": "NOSUCHCODE", "email": "nobody@test.de", "password": "supersecret-pw"},
        )
    assert response.status_code == 400


async def test_invite_redeem_already_consumed(test_engine: AsyncEngine) -> None:
    invite, _ = await make_invite(test_engine, consumed=True)
    with TestClient(app) as client:
        response = client.post(
            "/auth/invite/redeem",
            json={"code": invite.code, "email": invite.email, "password": "supersecret-pw"},
        )
    assert response.status_code == 400


async def test_invite_redeem_expired(test_engine: AsyncEngine) -> None:
    invite, _ = await make_invite(test_engine, expires_in_days=-1)
    with TestClient(app) as client:
        response = client.post(
            "/auth/invite/redeem",
            json={"code": invite.code, "email": invite.email, "password": "supersecret-pw"},
        )
    assert response.status_code == 400


async def test_invite_info_happy_path(test_engine: AsyncEngine) -> None:
    invite, _ = await make_invite(test_engine)
    with TestClient(app) as client:
        response = client.get(f"/auth/invite/{invite.code}")
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == invite.email
    assert body["role"] == invite.role.value
    assert body["organization_name"]  # non-empty
    assert "expires_at" in body


async def test_invite_info_unknown_returns_404(test_engine: AsyncEngine) -> None:
    with TestClient(app) as client:
        response = client.get("/auth/invite/NOSUCHCODE")
    assert response.status_code == 404


async def test_invite_info_consumed_returns_404(test_engine: AsyncEngine) -> None:
    """Consumed invites must look identical to never-existed ones over
    the wire — anything else would leak that the code was real once."""
    invite, _ = await make_invite(test_engine, consumed=True)
    with TestClient(app) as client:
        response = client.get(f"/auth/invite/{invite.code}")
    assert response.status_code == 404


async def test_invite_info_expired_returns_404(test_engine: AsyncEngine) -> None:
    invite, _ = await make_invite(test_engine, expires_in_days=-1)
    with TestClient(app) as client:
        response = client.get(f"/auth/invite/{invite.code}")
    assert response.status_code == 404


async def test_login_happy_path(test_engine: AsyncEngine) -> None:
    _, email, password = await make_user(test_engine)
    with TestClient(app) as client:
        response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["user"]["email"] == email


async def test_login_wrong_password(test_engine: AsyncEngine) -> None:
    _, email, _ = await make_user(test_engine)
    with TestClient(app) as client:
        response = client.post("/auth/login", json={"email": email, "password": "definitely-wrong"})
    assert response.status_code == 401


async def test_login_unknown_email(test_engine: AsyncEngine) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/auth/login", json={"email": "noone@test.de", "password": "whatever-1234"}
        )
    assert response.status_code == 401


async def test_refresh_rotates_and_invalidates_old(test_engine: AsyncEngine) -> None:
    _, email, password = await make_user(test_engine)
    with TestClient(app) as client:
        first = client.post("/auth/login", json={"email": email, "password": password}).json()
        old_refresh = first["refresh_token"]

        rotated = client.post("/auth/refresh", json={"refresh_token": old_refresh})
        assert rotated.status_code == 200
        new_refresh = rotated.json()["refresh_token"]
        assert new_refresh != old_refresh

        # Old refresh token must now be rejected.
        old_again = client.post("/auth/refresh", json={"refresh_token": old_refresh})
        assert old_again.status_code == 401


async def test_refresh_invalid_token(test_engine: AsyncEngine) -> None:
    with TestClient(app) as client:
        response = client.post("/auth/refresh", json={"refresh_token": "not.a.jwt"})
    assert response.status_code == 401


async def test_logout_revokes_session(test_engine: AsyncEngine) -> None:
    _, email, password = await make_user(test_engine)
    with TestClient(app) as client:
        login_body = client.post("/auth/login", json={"email": email, "password": password}).json()
        refresh_token = login_body["refresh_token"]
        logout = client.post("/auth/logout", json={"refresh_token": refresh_token})
        assert logout.status_code == 204
        # Refresh with the revoked token is now rejected.
        refresh = client.post("/auth/refresh", json={"refresh_token": refresh_token})
        assert refresh.status_code == 401

    # Belt-and-suspenders: also verify the row was actually flagged.
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        revoked = await s.scalars(
            select(Session)
            .where(Session.revoked_at.isnot(None))
            .where(Session.revoked_at > datetime.now(UTC) - timedelta(minutes=1))
        )
        assert len(revoked.all()) >= 1


# Silence unused-import warning for UserRole — re-exported from factories.
_ = UserRole
