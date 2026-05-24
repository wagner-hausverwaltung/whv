import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.integrations.impower.client import get_impower_client
from app.integrations.impower.sync import SyncStats
from app.main import app
from app.models import Property
from app.tests._factories import make_org, make_property


def _unique_impower_id() -> int:
    """A pseudo-impower id outside the realistic range, unique per test."""
    return 10**9 + (uuid.uuid4().int >> 96)


class _StubImpowerClient:
    """No-op stand-in; sync functions get monkeypatched so the client is never called."""

    async def __aenter__(self) -> "_StubImpowerClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None


@pytest_asyncio.fixture
async def override_impower_client() -> AsyncIterator[None]:
    async def _override() -> AsyncIterator[_StubImpowerClient]:
        yield _StubImpowerClient()

    app.dependency_overrides[get_impower_client] = _override
    yield
    app.dependency_overrides.pop(get_impower_client, None)


async def test_delete_soft_deletes_local_row(
    test_engine: AsyncEngine, override_impower_client: None
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    impower_id = _unique_impower_id()

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        row = await s.get(Property, prop.id)
        assert row is not None
        row.impower_id = impower_id
        await s.commit()

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/impower",
            json={
                "connectionId": 7,
                "entityType": "properties",
                "entityId": impower_id,
                "eventType": "DELETE",
            },
        )
    assert response.status_code == 200
    assert response.json()["status"] == "processed"

    async with sm() as s:
        row = await s.get(Property, prop.id)
        assert row is not None
        assert row.deleted_at is not None


async def test_duplicate_event_is_acked_without_reprocessing(
    test_engine: AsyncEngine, override_impower_client: None
) -> None:
    impower_id = _unique_impower_id()
    payload = {
        "connectionId": 7,
        "entityType": "properties",
        "entityId": impower_id,
        "eventType": "DELETE",
    }
    with TestClient(app) as client:
        first = client.post("/webhooks/impower", json=payload)
        second = client.post("/webhooks/impower", json=payload)

    assert first.status_code == 200
    assert first.json()["status"] == "processed"
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"


async def test_unsupported_entity_type_is_ignored(
    test_engine: AsyncEngine, override_impower_client: None
) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/webhooks/impower",
            json={
                "connectionId": 7,
                "entityType": "buildings",  # not yet mirrored
                "entityId": _unique_impower_id(),
                "eventType": "CREATE",
            },
        )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


async def test_malformed_payload_returns_422(test_engine: AsyncEngine) -> None:
    with TestClient(app) as client:
        response = client.post("/webhooks/impower", json={"foo": "bar"})
    assert response.status_code == 422


async def test_create_event_triggers_sync_function(
    test_engine: AsyncEngine,
    override_impower_client: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"properties": 0, "units": 0, "contracts": 0, "contacts": 0}

    async def make_stub(name: str) -> Any:
        async def stub(session: Any, client: Any) -> SyncStats:
            calls[name] += 1
            return SyncStats()

        return stub

    monkeypatch.setattr("app.api.v1.webhooks.sync_properties", await make_stub("properties"))
    monkeypatch.setattr("app.api.v1.webhooks.sync_units", await make_stub("units"))
    monkeypatch.setattr("app.api.v1.webhooks.sync_contracts", await make_stub("contracts"))
    monkeypatch.setattr("app.api.v1.webhooks.sync_contacts", await make_stub("contacts"))

    with TestClient(app) as client:
        for entity_type in ("properties", "units", "contracts", "contacts"):
            r = client.post(
                "/webhooks/impower",
                json={
                    "connectionId": 7,
                    "entityType": entity_type,
                    "entityId": _unique_impower_id(),
                    "eventType": "CREATE",
                },
            )
            assert r.status_code == 200
            assert r.json()["status"] == "processed"

    assert calls == {"properties": 1, "units": 1, "contracts": 1, "contacts": 1}
