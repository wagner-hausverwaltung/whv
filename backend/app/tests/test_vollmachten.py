"""Digitale Vollmacht (ETV proxy, ADR-0017) — owner grant+sign+download,
duplicate guard, revoke+re-grant, Mieter-cannot-grant, admin proxy register,
cross-org isolation.
"""

import base64
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.config import get_settings
from app.main import app
from app.models import AssemblyStatus, EtvAssembly, UserRole
from app.models.contract import ContractType
from app.tests._factories import (
    make_contact_with_contract_link,
    make_org,
    make_property,
    make_user,
)

# A real 1x1 PNG so the signature actually composites (not just the fallback).
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)


@pytest_asyncio.fixture
async def tmp_vollmacht_dir(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[str]:
    tmp_dir = tmp_path_factory.mktemp("whv-vollmachten")
    monkeypatch.setenv("VOLLMACHT_PDF_DIR", str(tmp_dir))
    get_settings.cache_clear()
    try:
        yield str(tmp_dir)
    finally:
        get_settings.cache_clear()


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return str(r.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _unique_impower() -> int:
    return uuid.uuid4().int % 2_000_000_000


async def _make_assembly(engine: AsyncEngine, *, org: Any, prop: Any) -> EtvAssembly:
    sm = async_sessionmaker(engine, expire_on_commit=False)
    start = datetime.now(UTC) + timedelta(days=14)
    async with sm() as s:
        assembly = EtvAssembly(
            organization_id=org.id,
            property_id=prop.id,
            title="Ordentliche Eigentümerversammlung 2026",
            description="",
            status=AssemblyStatus.GEPLANT,
            scheduled_start=start,
            scheduled_end=start + timedelta(hours=2),
            location="Gemeinschaftsraum",
        )
        s.add(assembly)
        await s.commit()
        await s.refresh(assembly)
    return assembly


async def _setup(
    engine: AsyncEngine, *, member_role: UserRole = UserRole.EIGENTUEMER
) -> dict[str, Any]:
    org = await make_org(engine)
    _, v_email, v_pw = await make_user(engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(engine, org=org)
    member_impower = _unique_impower()
    _, m_email, m_pw = await make_user(
        engine, org=org, role=member_role, contact_id_impower=member_impower
    )
    await make_contact_with_contract_link(
        engine,
        org=org,
        prop=prop,
        contact_impower_id=member_impower,
        contract_type=ContractType.OWNER if member_role != UserRole.MIETER else ContractType.TENANT,
    )
    assembly = await _make_assembly(engine, org=org, prop=prop)
    return {
        "org": org,
        "prop": prop,
        "assembly": assembly,
        "v_token": _login(v_email, v_pw),
        "m_token": _login(m_email, m_pw),
    }


def _grant(
    client: TestClient, token: str, assembly_id: uuid.UUID, *, proxy: str = "Dirk Ullrich"
) -> Any:
    return client.post(
        f"/me/assemblies/{assembly_id}/vollmacht",
        headers=_auth(token),
        data={"proxy_name": proxy, "scope_note": "Nur TOP 3"},
        files={"signature": ("sig.png", _PNG_1X1, "image/png")},
    )


async def test_owner_grants_and_downloads_vollmacht(
    test_engine: AsyncEngine, tmp_vollmacht_dir: str
) -> None:
    ctx = await _setup(test_engine)
    aid = ctx["assembly"].id
    with TestClient(app) as client:
        r = _grant(client, ctx["m_token"], aid)
        assert r.status_code == 201, r.text
        v = r.json()
        assert v["proxy_name"] == "Dirk Ullrich"
        assert v["status"] == "SIGNED"
        assert v["has_pdf"] is True
        assert v["principal_name"]  # resolved server-side

        # my active vollmacht is now fetchable
        r_get = client.get(f"/me/assemblies/{aid}/vollmacht", headers=_auth(ctx["m_token"]))
        assert r_get.status_code == 200
        assert r_get.json()["id"] == v["id"]

        # and the PDF downloads
        r_pdf = client.get(f"/me/vollmachten/{v['id']}/document.pdf", headers=_auth(ctx["m_token"]))
        assert r_pdf.status_code == 200
        assert r_pdf.content[:5] == b"%PDF-"


async def test_duplicate_vollmacht_rejected(
    test_engine: AsyncEngine, tmp_vollmacht_dir: str
) -> None:
    ctx = await _setup(test_engine)
    aid = ctx["assembly"].id
    with TestClient(app) as client:
        assert _grant(client, ctx["m_token"], aid).status_code == 201
        r2 = _grant(client, ctx["m_token"], aid)
        assert r2.status_code == 400
        assert "bereits" in r2.json()["detail"].lower()


async def test_revoke_then_regrant(test_engine: AsyncEngine, tmp_vollmacht_dir: str) -> None:
    ctx = await _setup(test_engine)
    aid = ctx["assembly"].id
    with TestClient(app) as client:
        v = _grant(client, ctx["m_token"], aid).json()
        r_rev = client.post(f"/me/vollmachten/{v['id']}/revoke", headers=_auth(ctx["m_token"]))
        assert r_rev.status_code == 200
        assert r_rev.json()["status"] == "REVOKED"
        # no active vollmacht now
        assert (
            client.get(f"/me/assemblies/{aid}/vollmacht", headers=_auth(ctx["m_token"])).status_code
            == 404
        )
        # can grant a fresh one
        assert _grant(client, ctx["m_token"], aid).status_code == 201


async def test_mieter_cannot_grant(test_engine: AsyncEngine, tmp_vollmacht_dir: str) -> None:
    ctx = await _setup(test_engine, member_role=UserRole.MIETER)
    aid = ctx["assembly"].id
    with TestClient(app) as client:
        r = _grant(client, ctx["m_token"], aid)
        assert r.status_code == 403


async def test_admin_register_lists_vollmachten(
    test_engine: AsyncEngine, tmp_vollmacht_dir: str
) -> None:
    ctx = await _setup(test_engine)
    aid = ctx["assembly"].id
    with TestClient(app) as client:
        v = _grant(client, ctx["m_token"], aid).json()
        r = client.get(f"/admin/assemblies/{aid}/vollmachten", headers=_auth(ctx["v_token"]))
        assert r.status_code == 200
        rows = r.json()
        assert any(row["id"] == v["id"] for row in rows)
        row = next(row for row in rows if row["id"] == v["id"])
        assert row["principal_email"]  # enriched for the register
        # admin can download it too
        r_pdf = client.get(
            f"/admin/vollmachten/{v['id']}/document.pdf", headers=_auth(ctx["v_token"])
        )
        assert r_pdf.status_code == 200


async def test_cross_org_isolation(test_engine: AsyncEngine, tmp_vollmacht_dir: str) -> None:
    ctx_a = await _setup(test_engine)
    ctx_b = await _setup(test_engine)
    aid_a = ctx_a["assembly"].id
    with TestClient(app) as client:
        # org B member can't grant on org A's assembly
        assert _grant(client, ctx_b["m_token"], aid_a).status_code == 404
        # org B Verwalter can't read org A's register
        assert (
            client.get(
                f"/admin/assemblies/{aid_a}/vollmachten", headers=_auth(ctx_b["v_token"])
            ).status_code
            == 404
        )
