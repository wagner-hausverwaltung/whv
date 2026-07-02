"""Admin /properties list enrichment: per-property unit count + an
'open ETV' flag (True when a WEG has no non-cancelled assembly scheduled
in the current calendar year; SEV/Mietverwaltung never get the flag)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.main import app
from app.models import AssemblyStatus, EtvAssembly, PropertyType, UserRole
from app.tests._factories import make_org, make_property, make_unit, make_user


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return str(r.json()["access_token"])


async def _add_assembly(
    sm: async_sessionmaker[Any],
    *,
    org_id: Any,
    property_id: Any,
    start: datetime,
    status: AssemblyStatus = AssemblyStatus.GEPLANT,
) -> None:
    async with sm() as s:
        s.add(
            EtvAssembly(
                organization_id=org_id,
                property_id=property_id,
                title="ETV",
                location="Vor Ort",
                scheduled_start=start,
                scheduled_end=start + timedelta(hours=2),
                status=status,
            )
        )
        await s.commit()


async def test_admin_properties_units_count_and_open_etv(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    _, vemail, vpw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    now = datetime.now(UTC)

    # A: WEG, 2 units + a current-year ETV → not open, count 2.
    prop_a = await make_property(test_engine, org=org, name="AAA Haus", type=PropertyType.OWNER)
    await make_unit(test_engine, org=org, prop=prop_a)
    await make_unit(test_engine, org=org, prop=prop_a)
    await _add_assembly(sm, org_id=org.id, property_id=prop_a.id, start=now)

    # B: WEG, no units, only a CANCELLED current-year ETV → still open.
    prop_b = await make_property(test_engine, org=org, name="BBB Haus", type=PropertyType.OWNER)
    await _add_assembly(
        sm,
        org_id=org.id,
        property_id=prop_b.id,
        start=now,
        status=AssemblyStatus.ABGESAGT,
    )

    # C: WEG, only a PRIOR-year ETV → open (missing this year's).
    prop_c = await make_property(test_engine, org=org, name="CCC Haus", type=PropertyType.OWNER)
    await _add_assembly(sm, org_id=org.id, property_id=prop_c.id, start=now - timedelta(days=400))

    # D/E: SEV (STRATA) and Mietverwaltung (RENTAL) hold no ETVs → never
    # flagged, even without any assembly.
    await make_property(test_engine, org=org, name="DDD SEV", type=PropertyType.STRATA)
    await make_property(test_engine, org=org, name="EEE MV", type=PropertyType.RENTAL)

    token = _login(vemail, vpw)
    with TestClient(app) as client:
        r = client.get("/admin/properties", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    by_name = {p["name"]: p for p in r.json()}

    assert by_name["AAA Haus"]["units_count"] == 2
    assert by_name["AAA Haus"]["needs_current_year_etv"] is False

    # Cancelled current-year ETV does not satisfy the yearly requirement.
    assert by_name["BBB Haus"]["units_count"] == 0
    assert by_name["BBB Haus"]["needs_current_year_etv"] is True

    # A prior-year ETV does not count as this year's.
    assert by_name["CCC Haus"]["needs_current_year_etv"] is True

    # SEV / Mietverwaltung never need an ETV.
    assert by_name["DDD SEV"]["needs_current_year_etv"] is False
    assert by_name["EEE MV"]["needs_current_year_etv"] is False


async def test_property_selection_persists_org_wide(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    _, v1email, v1pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    _, v2email, v2pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop_a = await make_property(test_engine, org=org, name="Sel A")
    prop_b = await make_property(test_engine, org=org, name="Sel B")

    h1 = {"Authorization": f"Bearer {_login(v1email, v1pw)}"}
    with TestClient(app) as client:
        # Empty until something is selected.
        r0 = client.get("/admin/property-selection", headers=h1)
        assert r0.status_code == 200
        assert r0.json()["property_ids"] == []

        # V1 saves a selection containing a bogus id + a duplicate, which
        # the endpoint must drop while preserving order.
        bogus = str(uuid.uuid4())
        r1 = client.put(
            "/admin/property-selection",
            headers=h1,
            json={
                "property_ids": [
                    str(prop_a.id),
                    bogus,
                    str(prop_b.id),
                    str(prop_a.id),
                ]
            },
        )
        assert r1.status_code == 200
        assert r1.json()["property_ids"] == [str(prop_a.id), str(prop_b.id)]

    # A second Verwalter of the same org sees the shared selection.
    h2 = {"Authorization": f"Bearer {_login(v2email, v2pw)}"}
    with TestClient(app) as client:
        r2 = client.get("/admin/property-selection", headers=h2)
        assert r2.status_code == 200
        assert r2.json()["property_ids"] == [str(prop_a.id), str(prop_b.id)]
