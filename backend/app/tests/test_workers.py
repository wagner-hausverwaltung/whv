from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from app.integrations.impower.sync import SyncStats


async def test_sync_all_async_calls_each_sync_in_order(
    test_engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Celery task wrapper runs sync_X in the right order with the same session+client."""
    calls: list[str] = []

    def stub_factory(name: str) -> Callable[[Any, Any], Awaitable[SyncStats]]:
        async def stub(session: Any, client: Any) -> SyncStats:
            calls.append(name)
            return SyncStats(fetched=1, upserted=1)

        return stub

    monkeypatch.setattr("app.workers.tasks.sync_properties", stub_factory("properties"))
    monkeypatch.setattr("app.workers.tasks.sync_units", stub_factory("units"))
    monkeypatch.setattr("app.workers.tasks.sync_contacts", stub_factory("contacts"))
    monkeypatch.setattr("app.workers.tasks.sync_contracts", stub_factory("contracts"))
    monkeypatch.setattr("app.workers.tasks.sync_documents", stub_factory("documents"))

    from app.workers.tasks import _sync_all_async

    counts = await _sync_all_async()

    assert calls == ["properties", "units", "contacts", "contracts", "documents"]
    assert counts == {
        "properties": 1,
        "units": 1,
        "contacts": 1,
        "contracts": 1,
        "documents": 1,
    }


def test_celery_app_has_nightly_schedule() -> None:
    from app.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert "sync-all-impower-nightly" in schedule
    entry = schedule["sync-all-impower-nightly"]
    assert entry["task"] == "app.workers.tasks.sync_all_impower"


def test_celery_app_has_periodic_contacts_sync() -> None:
    """Contacts refresh frequently (safety net for the non-firing webhook)."""
    from app.workers.celery_app import celery_app
    from app.workers.tasks import sync_contacts_periodic

    schedule = celery_app.conf.beat_schedule
    assert "sync-contacts-periodic" in schedule
    assert schedule["sync-contacts-periodic"]["task"] == "app.workers.tasks.sync_contacts_periodic"
    # task is registered under its declared name
    assert "app.workers.tasks.sync_contacts_periodic" in celery_app.tasks
    assert callable(sync_contacts_periodic)
