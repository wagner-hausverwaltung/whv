"""Tests for notification preferences: the filter helper (opt-out
semantics), the get/set service, and the /me/notification-settings API.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.main import app
from app.models import NotificationCategory, NotificationChannel, UserRole
from app.services import notification_prefs
from app.tests._factories import make_org, make_user


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    token: str = r.json()["access_token"]
    return token


async def test_filter_opt_out_default_includes_everyone(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    u1, _, _ = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    u2, _, _ = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        out = await notification_prefs.filter_user_ids(
            s,
            user_ids=[u1.id, u2.id],
            category=NotificationCategory.TICKET,
            channel=NotificationChannel.PUSH,
        )
    # No saved rows → everyone stays in (opt-out).
    assert set(out) == {u1.id, u2.id}


async def test_filter_respects_explicit_off_per_channel(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    u1, _, _ = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    u2, _, _ = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        # u1: TICKET push OFF, email ON.
        await notification_prefs.set_settings(
            s,
            user_id=u1.id,
            settings={NotificationCategory.TICKET: (False, True)},
        )
        await s.commit()
    async with sm() as s:
        push_out = await notification_prefs.filter_user_ids(
            s,
            user_ids=[u1.id, u2.id],
            category=NotificationCategory.TICKET,
            channel=NotificationChannel.PUSH,
        )
        email_out = await notification_prefs.filter_user_ids(
            s,
            user_ids=[u1.id, u2.id],
            category=NotificationCategory.TICKET,
            channel=NotificationChannel.EMAIL,
        )
        # A different category is untouched by the TICKET row.
        other = await notification_prefs.filter_user_ids(
            s,
            user_ids=[u1.id],
            category=NotificationCategory.ANNOUNCEMENT,
            channel=NotificationChannel.PUSH,
        )
    assert u1.id not in push_out
    assert u2.id in push_out
    assert {u1.id, u2.id} <= set(email_out)
    assert u1.id in other


async def test_get_effective_defaults_all_on(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    u, _, _ = await make_user(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        eff = await notification_prefs.get_effective_settings(s, user_id=u.id)
    assert len(eff) == 7
    assert all(push and email for (push, email) in eff.values())


async def test_settings_api_get_put_roundtrip(test_engine: AsyncEngine) -> None:
    _, email, password = await make_user(test_engine, role=UserRole.EIGENTUEMER)
    token = _login(email, password)
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        r = client.get("/me/notification-settings", headers=headers)
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 7
        assert all(i["push"] and i["email"] for i in items)

        new_items = [
            {
                "category": i["category"],
                "push": False if i["category"] == "ETV_COMMENT" else i["push"],
                "email": i["email"],
            }
            for i in items
        ]
        r2 = client.put(
            "/me/notification-settings",
            headers=headers,
            json={"items": new_items},
        )
        assert r2.status_code == 200
        got = {i["category"]: i for i in r2.json()["items"]}
        assert got["ETV_COMMENT"]["push"] is False
        assert got["ETV_COMMENT"]["email"] is True

        # Persistence: a fresh GET reflects the change.
        r3 = client.get("/me/notification-settings", headers=headers)
        got3 = {i["category"]: i for i in r3.json()["items"]}
        assert got3["ETV_COMMENT"]["push"] is False
        assert got3["TICKET"]["push"] is True
