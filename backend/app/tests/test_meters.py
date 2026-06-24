"""Zähler (meter) management — admin CRUD + bulk, member reading submission
(with/without photo), OCR preview (provider-unavailable + stubbed), CSV
export, cross-org isolation, and the delete-guard for meters with history.
"""

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import get_settings
from app.integrations.llm.base import LLMCallStats, LLMResult
from app.main import app
from app.models import UserRole
from app.services import meters as meters_svc
from app.tests._factories import (
    make_contact_with_contract_link,
    make_org,
    make_property,
    make_unit,
    make_user,
)

# --- fixtures / helpers -------------------------------------------------------


@pytest_asyncio.fixture
async def tmp_meter_photo_dir(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[str]:
    """Point the photo storage at a tmpdir (mirror of test_ticket_attachments)."""
    tmp_dir = tmp_path_factory.mktemp("whv-meter-readings")
    monkeypatch.setenv("METER_READING_PHOTO_DIR", str(tmp_dir))
    get_settings.cache_clear()
    try:
        yield str(tmp_dir)
    finally:
        get_settings.cache_clear()


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    token: str = r.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _unique_impower() -> int:
    # Contact.impower_id is unique across the shared test DB.
    return uuid.uuid4().int % 2_000_000_000


async def _setup(engine: AsyncEngine) -> dict[str, object]:
    """org + Verwalter + an EIGENTUEMER member with contract access to a
    READY property. Returns creds + the property."""
    org = await make_org(engine)
    _, v_email, v_pw = await make_user(engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(engine, org=org)
    member_impower = _unique_impower()
    _, m_email, m_pw = await make_user(
        engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=member_impower
    )
    await make_contact_with_contract_link(
        engine, org=org, prop=prop, contact_impower_id=member_impower
    )
    return {
        "org": org,
        "prop": prop,
        "v_token": _login(v_email, v_pw),
        "m_token": _login(m_email, m_pw),
    }


def _create_meter(
    client: TestClient, token: str, property_id: uuid.UUID, **over: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "meter_number": f"Z-{uuid.uuid4().hex[:8]}",
        "meter_type": "STROM",
        "description": "Allgemeinstrom",
    }
    body.update(over)
    r = client.post(f"/admin/properties/{property_id}/meters", headers=_auth(token), json=body)
    assert r.status_code == 201, r.text
    result: dict[str, Any] = r.json()
    return result


# --- tests --------------------------------------------------------------------


async def test_verwalter_create_meter_defaults_unit_label(test_engine: AsyncEngine) -> None:
    ctx = await _setup(test_engine)
    prop_id = ctx["prop"].id  # type: ignore[attr-defined]
    with TestClient(app) as client:
        meter = _create_meter(client, ctx["v_token"], prop_id)  # type: ignore[arg-type]
        assert meter["meter_type"] == "STROM"
        assert meter["unit_label"] == "kWh"  # defaulted from type
        assert meter["reading_count"] == 0
        assert meter["latest_reading_value"] is None

        # appears in the admin list
        r = client.get(f"/admin/properties/{prop_id}/meters", headers=_auth(ctx["v_token"]))  # type: ignore[arg-type]
        assert r.status_code == 200
        assert any(m["id"] == meter["id"] for m in r.json())


async def test_member_submits_reading_and_sees_history(test_engine: AsyncEngine) -> None:
    ctx = await _setup(test_engine)
    prop_id = ctx["prop"].id  # type: ignore[attr-defined]
    with TestClient(app) as client:
        meter = _create_meter(client, ctx["v_token"], prop_id)  # type: ignore[arg-type]

        # member sees the meter on the property
        r_list = client.get(
            f"/me/properties/{prop_id}/meters",
            headers=_auth(ctx["m_token"]),  # type: ignore[arg-type]
        )
        assert r_list.status_code == 200, r_list.text
        assert any(m["id"] == meter["id"] for m in r_list.json())

        # member submits a reading (no photo → urlencoded form)
        r_sub = client.post(
            f"/me/meters/{meter['id']}/readings",
            headers=_auth(ctx["m_token"]),  # type: ignore[arg-type]
            data={"value": "1234.5", "read_on": "2026-06-01", "source": "MANUAL"},
        )
        assert r_sub.status_code == 201, r_sub.text
        reading = r_sub.json()
        assert Decimal(str(reading["value"])) == Decimal("1234.5")
        assert reading["has_photo"] is False

        # shows in history
        r_hist = client.get(
            f"/me/meters/{meter['id']}/readings",
            headers=_auth(ctx["m_token"]),  # type: ignore[arg-type]
        )
        assert r_hist.status_code == 200
        assert len(r_hist.json()) == 1

        # and the latest reading surfaces on the meter list
        r_list2 = client.get(
            f"/me/properties/{prop_id}/meters",
            headers=_auth(ctx["m_token"]),  # type: ignore[arg-type]
        )
        row = next(m for m in r_list2.json() if m["id"] == meter["id"])
        assert Decimal(str(row["latest_reading_value"])) == Decimal("1234.5")
        assert row["reading_count"] == 1


async def test_reading_with_photo_roundtrips(
    test_engine: AsyncEngine, tmp_meter_photo_dir: str
) -> None:
    ctx = await _setup(test_engine)
    prop_id = ctx["prop"].id  # type: ignore[attr-defined]
    photo = b"\x89PNG\r\n\x1a\n meter face"
    with TestClient(app) as client:
        meter = _create_meter(client, ctx["v_token"], prop_id)  # type: ignore[arg-type]
        r_sub = client.post(
            f"/me/meters/{meter['id']}/readings",
            headers=_auth(ctx["m_token"]),  # type: ignore[arg-type]
            data={"value": "42", "source": "OCR", "ocr_raw": "42"},
            files={"photo": ("meter.png", photo, "image/png")},
        )
        assert r_sub.status_code == 201, r_sub.text
        reading = r_sub.json()
        assert reading["has_photo"] is True
        assert reading["source"] == "OCR"

        r_down = client.get(
            f"/me/meters/{meter['id']}/readings/{reading['id']}/photo",
            headers=_auth(ctx["m_token"]),  # type: ignore[arg-type]
        )
        assert r_down.status_code == 200
        assert r_down.content == photo


async def test_ocr_preview_provider_unavailable_is_non_fatal(
    test_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No LLM provider configured → 200 with an empty suggestion, not a 5xx."""
    from app.integrations.llm.base import NullProvider

    monkeypatch.setattr(meters_svc, "get_llm_provider", lambda: NullProvider())
    ctx = await _setup(test_engine)
    prop_id = ctx["prop"].id  # type: ignore[attr-defined]
    with TestClient(app) as client:
        meter = _create_meter(client, ctx["v_token"], prop_id)  # type: ignore[arg-type]
        r = client.post(
            f"/me/meters/{meter['id']}/readings/ocr",
            headers=_auth(ctx["m_token"]),  # type: ignore[arg-type]
            files={"photo": ("m.jpg", b"\xff\xd8\xff fake jpeg", "image/jpeg")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["provider_available"] is False
        assert body["suggested_value"] is None


async def test_ocr_preview_with_stub_provider_coerces_value(
    test_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _StubLLM:
        name = "stub"

        async def extract_from_image(self, *, image_bytes, mime_type, prompt, response_schema):  # type: ignore[no-untyped-def]
            return LLMResult(
                payload=response_schema(reading="12345,6", meter_number="ABC-1", confidence=0.9),
                stats=LLMCallStats(model="stub", input_tokens=1, output_tokens=1, latency_ms=1),
            )

    monkeypatch.setattr(meters_svc, "get_llm_provider", lambda: _StubLLM())
    ctx = await _setup(test_engine)
    prop_id = ctx["prop"].id  # type: ignore[attr-defined]
    with TestClient(app) as client:
        meter = _create_meter(client, ctx["v_token"], prop_id)  # type: ignore[arg-type]
        r = client.post(
            f"/me/meters/{meter['id']}/readings/ocr",
            headers=_auth(ctx["m_token"]),  # type: ignore[arg-type]
            files={"photo": ("m.jpg", b"\xff\xd8\xff body", "image/jpeg")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["provider_available"] is True
        assert Decimal(str(body["suggested_value"])) == Decimal("12345.6")
        assert body["meter_number"] == "ABC-1"


async def test_bulk_create_collects_per_row_errors(test_engine: AsyncEngine) -> None:
    ctx = await _setup(test_engine)
    org = ctx["org"]
    prop = ctx["prop"]
    unit = await make_unit(test_engine, org=org, prop=prop)  # type: ignore[arg-type]
    foreign_unit_id = str(uuid.uuid4())  # not a unit of this property
    with TestClient(app) as client:
        r = client.post(
            f"/admin/properties/{prop.id}/meters/bulk",  # type: ignore[attr-defined]
            headers=_auth(ctx["v_token"]),  # type: ignore[arg-type]
            json={
                "meters": [
                    {"meter_number": f"OK-{uuid.uuid4().hex[:6]}", "meter_type": "GAS"},
                    {
                        "meter_number": f"UNIT-{uuid.uuid4().hex[:6]}",
                        "meter_type": "WASSER",
                        "unit_id": str(unit.id),
                    },
                    {
                        "meter_number": f"BAD-{uuid.uuid4().hex[:6]}",
                        "meter_type": "STROM",
                        "unit_id": foreign_unit_id,
                    },
                ]
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert len(body["created"]) == 2
        assert len(body["errors"]) == 1
        assert body["errors"][0]["index"] == 2


async def test_delete_blocked_when_readings_exist(test_engine: AsyncEngine) -> None:
    ctx = await _setup(test_engine)
    prop_id = ctx["prop"].id  # type: ignore[attr-defined]
    with TestClient(app) as client:
        meter = _create_meter(client, ctx["v_token"], prop_id)  # type: ignore[arg-type]
        # empty meter deletes fine
        r_del_ok = client.delete(
            f"/admin/meters/{meter['id']}",
            headers=_auth(ctx["v_token"]),  # type: ignore[arg-type]
        )
        assert r_del_ok.status_code == 204

        meter2 = _create_meter(client, ctx["v_token"], prop_id)  # type: ignore[arg-type]
        client.post(
            f"/me/meters/{meter2['id']}/readings",
            headers=_auth(ctx["m_token"]),  # type: ignore[arg-type]
            data={"value": "10"},
        )
        r_del = client.delete(
            f"/admin/meters/{meter2['id']}",
            headers=_auth(ctx["v_token"]),  # type: ignore[arg-type]
        )
        assert r_del.status_code == 409
        # but deactivate works
        r_patch = client.patch(
            f"/admin/meters/{meter2['id']}",
            headers=_auth(ctx["v_token"]),  # type: ignore[arg-type]
            json={"is_active": False},
        )
        assert r_patch.status_code == 200
        assert r_patch.json()["is_active"] is False


async def test_csv_export_lists_readings(test_engine: AsyncEngine) -> None:
    ctx = await _setup(test_engine)
    prop_id = ctx["prop"].id  # type: ignore[attr-defined]
    with TestClient(app) as client:
        meter = _create_meter(client, ctx["v_token"], prop_id, meter_number="CSV-METER-1")  # type: ignore[arg-type]
        client.post(
            f"/me/meters/{meter['id']}/readings",
            headers=_auth(ctx["m_token"]),  # type: ignore[arg-type]
            data={"value": "777.0", "read_on": "2026-06-10"},
        )
        r = client.get(
            f"/admin/properties/{prop_id}/meters/readings.csv",
            headers=_auth(ctx["v_token"]),  # type: ignore[arg-type]
        )
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        assert "CSV-METER-1" in r.text
        assert "Zählernummer" in r.text


async def test_member_cannot_create_meter(test_engine: AsyncEngine) -> None:
    ctx = await _setup(test_engine)
    prop_id = ctx["prop"].id  # type: ignore[attr-defined]
    with TestClient(app) as client:
        r = client.post(
            f"/admin/properties/{prop_id}/meters",
            headers=_auth(ctx["m_token"]),  # type: ignore[arg-type]
            json={"meter_number": "X", "meter_type": "STROM"},
        )
        assert r.status_code == 403


async def test_cross_org_meter_isolation(test_engine: AsyncEngine) -> None:
    ctx_a = await _setup(test_engine)
    ctx_b = await _setup(test_engine)
    prop_a = ctx_a["prop"].id  # type: ignore[attr-defined]
    with TestClient(app) as client:
        meter_a = _create_meter(client, ctx_a["v_token"], prop_a)  # type: ignore[arg-type]
        # Org B member can't read org A's meter or submit to it.
        r_hist = client.get(
            f"/me/meters/{meter_a['id']}/readings",
            headers=_auth(ctx_b["m_token"]),  # type: ignore[arg-type]
        )
        assert r_hist.status_code == 404
        r_sub = client.post(
            f"/me/meters/{meter_a['id']}/readings",
            headers=_auth(ctx_b["m_token"]),  # type: ignore[arg-type]
            data={"value": "1"},
        )
        assert r_sub.status_code == 404
        # Org B Verwalter can't edit org A's meter either.
        r_patch = client.patch(
            f"/admin/meters/{meter_a['id']}",
            headers=_auth(ctx_b["v_token"]),  # type: ignore[arg-type]
            json={"description": "hijack"},
        )
        assert r_patch.status_code == 404
