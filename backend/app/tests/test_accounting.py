"""Jahresabrechnung tracker — member read + Verwalter tick."""

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.main import app
from app.models import UserRole
from app.tests._factories import make_org, make_property, make_user


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return str(r.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_progress_defaults_all_open(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.get(f"/me/properties/{prop.id}/accounting?year=2025", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 9
    assert body["done_count"] == 0
    assert [s["code"] for s in body["stages"]] == ["A", "B", "C", "D", "E", "F", "G", "H", "I"]
    assert all(s["done"] is False for s in body["stages"])


async def test_tick_and_untick_stage(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.put(
            f"/admin/properties/{prop.id}/accounting/2025/stages/C",
            headers=_auth(token),
            json={"done": True, "note": "an Techem versendet"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["done_count"] == 1
        c = next(s for s in body["stages"] if s["code"] == "C")
        assert c["done"] is True and c["done_at"] is not None and c["note"] == "an Techem versendet"
        # Member read reflects it.
        g = client.get(f"/me/properties/{prop.id}/accounting?year=2025", headers=_auth(token))
        assert next(s for s in g.json()["stages"] if s["code"] == "C")["done"] is True
        # Untick.
        r2 = client.put(
            f"/admin/properties/{prop.id}/accounting/2025/stages/C",
            headers=_auth(token),
            json={"done": False},
        )
    assert r2.json()["done_count"] == 0
    assert next(s for s in r2.json()["stages"] if s["code"] == "C")["done_at"] is None


async def test_invalid_stage_code_400(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.put(
            f"/admin/properties/{prop.id}/accounting/2025/stages/Z",
            headers=_auth(token),
            json={"done": True},
        )
    assert r.status_code == 400


async def test_eigentuemer_cannot_tick(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.put(
            f"/admin/properties/{prop.id}/accounting/2025/stages/A",
            headers=_auth(token),
            json={"done": True},
        )
    assert r.status_code == 403


async def test_admin_board_lists_all_properties(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    p1 = await make_property(test_engine, org=org, name="WEG Alpha")
    await make_property(test_engine, org=org, name="WEG Beta")
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        client.put(
            f"/admin/properties/{p1.id}/accounting/2025/stages/A",
            headers=_auth(token),
            json={"done": True},
        ).raise_for_status()
        r = client.get("/admin/accounting?year=2025", headers=_auth(token))
    assert r.status_code == 200, r.text
    by_name = {row["property_name"]: row for row in r.json()}
    assert {"WEG Alpha", "WEG Beta"} <= set(by_name)
    assert by_name["WEG Alpha"]["done_count"] == 1
    assert by_name["WEG Beta"]["done_count"] == 0
    assert len(by_name["WEG Alpha"]["stages"]) == 9


async def test_admin_board_eigentuemer_forbidden(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.get("/admin/accounting", headers=_auth(token))
    assert r.status_code == 403


async def test_progress_cross_org_404(test_engine: AsyncEngine) -> None:
    org_a = await make_org(test_engine)
    prop = await make_property(test_engine, org=org_a)
    org_b = await make_org(test_engine)
    _, email, pw = await make_user(test_engine, org=org_b, role=UserRole.VERWALTER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.get(f"/me/properties/{prop.id}/accounting", headers=_auth(token))
    assert r.status_code == 404
