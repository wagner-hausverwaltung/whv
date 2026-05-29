"""Admin unit endpoints. Covers PUT /admin/units/{id}/distribution-keys,
which previously 500'd because it constructed AuditLog with the wrong
kwargs (resource_type/resource_id/details vs. the model's
target_type/target_id/payload_json)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.main import app
from app.models import AuditLog, UserRole
from app.tests._factories import make_org, make_property, make_unit, make_user


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return str(r.json()["access_token"])


async def test_update_distribution_keys_persists_and_writes_audit(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    _, vemail, vpw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org, name="Verteiler Haus")
    unit = await make_unit(test_engine, org=org, prop=prop)

    token = _login(vemail, vpw)
    body = {
        "voting_share": 123.45,
        "area_m2": 78.5,
        "heated_area_m2": 70.0,
        "persons": 2.0,
    }
    with TestClient(app) as client:
        r = client.put(
            f"/admin/units/{unit.id}/distribution-keys",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )

    # Regression: this used to 500 (AuditLog kwarg mismatch). It must 200.
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["voting_share"] == 123.45
    assert out["area_m2"] == 78.5
    assert out["heated_area_m2"] == 70.0
    assert out["persons"] == 2.0

    # The audit row must have been written with the model's real columns;
    # if the kwargs were wrong the request would have crashed before commit.
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        rows = (
            (
                await s.execute(
                    select(AuditLog).where(
                        AuditLog.action == "unit.distribution_keys.updated",
                        AuditLog.target_id == str(unit.id),
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    entry = rows[0]
    assert entry.target_type == "units"
    assert entry.actor_user_id is not None
    payload: dict[str, Any] = entry.payload_json or {}
    assert payload["voting_share"] == 123.45
    assert payload["persons"] == 2.0
