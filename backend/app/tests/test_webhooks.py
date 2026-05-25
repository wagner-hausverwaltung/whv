import hashlib
import hmac
import json
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


# --- HMAC signature verification (spec §15.1 #8) ----------------------------


async def test_impower_webhook_rejects_missing_signature(
    test_engine: AsyncEngine,
    override_impower_client: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a secret configured, an unsigned request → 401."""
    from app.config import get_settings

    monkeypatch.setenv("IMPOWER_WEBHOOK_SECRET", "shh-its-a-secret")
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            r = client.post(
                "/webhooks/impower",
                json={
                    "connectionId": 7,
                    "entityType": "properties",
                    "entityId": _unique_impower_id(),
                    "eventType": "CREATE",
                },
            )
        assert r.status_code == 401
        assert "signature" in r.json()["detail"].lower()
    finally:
        get_settings.cache_clear()


async def test_impower_webhook_accepts_correct_signature(
    test_engine: AsyncEngine,
    override_impower_client: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid HMAC-SHA256 hex digest in X-Impower-Signature → 200."""
    from app.config import get_settings

    secret = "shh-its-a-secret"
    monkeypatch.setenv("IMPOWER_WEBHOOK_SECRET", secret)
    get_settings.cache_clear()
    try:
        # Make the syncs no-ops so the test stays fast + offline.
        async def noop_sync(*args: Any, **kwargs: Any) -> SyncStats:
            return SyncStats(fetched=0, upserted=0, skipped=0)

        monkeypatch.setattr("app.api.v1.webhooks.sync_properties", noop_sync)

        payload = {
            "connectionId": 7,
            "entityType": "properties",
            "entityId": _unique_impower_id(),
            "eventType": "CREATE",
        }
        body = json.dumps(payload).encode("utf-8")
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        with TestClient(app) as client:
            r = client.post(
                "/webhooks/impower",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Impower-Signature": signature,
                },
            )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "processed"
    finally:
        get_settings.cache_clear()


async def test_impower_webhook_rejects_wrong_signature(
    test_engine: AsyncEngine,
    override_impower_client: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tampered body with a fixed signature → 401."""
    from app.config import get_settings

    monkeypatch.setenv("IMPOWER_WEBHOOK_SECRET", "shh-its-a-secret")
    get_settings.cache_clear()
    try:
        payload = {
            "connectionId": 7,
            "entityType": "properties",
            "entityId": _unique_impower_id(),
            "eventType": "CREATE",
        }
        with TestClient(app) as client:
            r = client.post(
                "/webhooks/impower",
                json=payload,
                headers={"X-Impower-Signature": "0" * 64},
            )
        assert r.status_code == 401
    finally:
        get_settings.cache_clear()
