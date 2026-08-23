"""Fahrtenbuch reports: Sunday review text + monthly statement mail."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, timedelta
from typing import Any

import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.config import get_settings
from app.main import app
from app.models import PropertyType, UserRole
from app.services.trip_reports import build_week_reviews, send_monthly_statements, week_bounds
from app.tests._factories import make_org, make_property, make_user


class _StubEmailClient:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(
        self, *, to: str | list[str], subject: str, html: str, text: str, **kw: Any
    ) -> str:
        self.sent.append(
            {"to": to, "subject": subject, "text": text, "attachments": kw.get("attachments")}
        )
        return f"sim-{uuid.uuid4()}"

    async def aclose(self) -> None:
        return None


@pytest_asyncio.fixture
async def stub() -> AsyncIterator[_StubEmailClient]:
    yield _StubEmailClient()


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    token: str = r.json()["access_token"]
    return token


async def test_week_review_and_monthly_statement(
    test_engine: AsyncEngine, stub: _StubEmailClient
) -> None:
    org = await make_org(test_engine)
    weg = await make_property(
        test_engine, org=org, name="WEG Burgstraße 6/8, 71254 Ditzingen", type=PropertyType.OWNER
    )
    mv = await make_property(test_engine, org=org, name="MV Karlstraße 5", type=PropertyType.RENTAL)
    user, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    start, _ = week_bounds()
    day = start.astimezone(UTC) + timedelta(days=1, hours=9)
    with TestClient(app) as client:
        h = {"Authorization": f"Bearer {token}"}
        for purpose, pid, km in (
            ("ETV", weg.id, 22),
            ("HANDWERKERTERMIN", mv.id, 8),
            (None, None, 3),
        ):
            body: dict[str, Any] = {
                "started_at": day.isoformat(),
                "ended_at": (day + timedelta(minutes=30)).isoformat(),
                "distance_m": km * 1000,
                "source": "MANUAL",
            }
            if purpose:
                body["purpose"] = purpose
            if pid:
                body["property_id"] = str(pid)
            assert client.post("/me/trips/complete", headers=h, json=body).status_code == 201
            day += timedelta(hours=2)

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        s_start, s_end = week_bounds()
        reviews = await build_week_reviews(s, org_id=org.id, start=s_start, end=s_end)
        mine = next(r for r in reviews if r.user_id == user.id)
        assert mine.trips == 3
        assert mine.distance_m == 33_000
        assert mine.properties == 2
        assert mine.open_trips == 1
        assert mine.billable_hints == [("WEG Burgstraße 6/8", 1)]
        assert "33,0 km" in mine.body and "2 Objekte" in mine.body
        assert "1 Fahrt unbestätigt" in mine.body
        assert "1 Rechnung möglich (WEG Burgstraße 6/8, ETV außerhalb)" in mine.body

        month = start.strftime("%Y-%m")
        n = await send_monthly_statements(
            s,
            org_id=org.id,
            settings=get_settings(),
            email_client=stub,  # type: ignore[arg-type]
            month=month,
        )
        assert n == 1
        mail = stub.sent[-1]
        assert mail["to"] == get_settings().trip_report_email
        assert f"Kilometergeld-Abrechnung {month}" in mail["subject"]
        assert mail["attachments"] and mail["attachments"][0]["filename"].endswith(".pdf")
        assert "Luis Wagner, Bozener Straße 12" in mail["text"]
