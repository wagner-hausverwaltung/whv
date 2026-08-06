"""Storno lookup cache: what happens when Impower is unavailable.

The failure path is the whole point of this module — on success it is a
plain memoised fetch. If a lookup fails we must keep the last known
answer (so cancelled invoices stay hidden) and stop hammering a
dependency that is already unwell.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.reversed_invoices import (
    _RETRY_AFTER_FAILURE_SECONDS,
    ReversedInvoiceCache,
)


class _FakeSettings:
    impower_api_base = "https://api.example/v2"
    impower_api_token = "tok"


class _FakeClient:
    """Stands in for ImpowerClient as an async context manager."""

    def __init__(self, result: set[int] | None, error: Exception | None) -> None:
        self._result = result
        self._error = error
        self.calls = 0

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def list_reversed_invoice_ids(self, property_id: int) -> set[int]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._result or set()


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> None:
    def factory(*_args: Any, **_kwargs: Any) -> _FakeClient:
        return client

    monkeypatch.setattr("app.integrations.impower.client.ImpowerClient", factory)


async def test_successful_lookup_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient({1, 2}, None)
    _patch_client(monkeypatch, client)
    cache = ReversedInvoiceCache()

    first = await cache.get(11227, _FakeSettings())  # type: ignore[arg-type]
    second = await cache.get(11227, _FakeSettings())  # type: ignore[arg-type]

    assert first == {1, 2}
    assert second == {1, 2}
    assert client.calls == 1  # second read served from cache


async def test_failure_keeps_the_last_known_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """A storno must not reappear for owners just because Impower blinked."""
    good = _FakeClient({42}, None)
    _patch_client(monkeypatch, good)
    cache = ReversedInvoiceCache(ttl_seconds=0.0)  # every read refetches
    assert await cache.get(11227, _FakeSettings()) == {42}  # type: ignore[arg-type]

    broken = _FakeClient(None, RuntimeError("impower down"))
    _patch_client(monkeypatch, broken)

    assert await cache.get(11227, _FakeSettings()) == {42}  # type: ignore[arg-type]


async def test_failure_backs_off_instead_of_retrying_every_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a backoff every vendor-tab request would pay the full
    Impower timeout for as long as the outage lasts."""
    broken = _FakeClient(None, RuntimeError("impower down"))
    _patch_client(monkeypatch, broken)
    cache = ReversedInvoiceCache(ttl_seconds=0.0)

    assert await cache.get(11227, _FakeSettings()) == set()  # type: ignore[arg-type]
    assert await cache.get(11227, _FakeSettings()) == set()  # type: ignore[arg-type]
    assert await cache.get(11227, _FakeSettings()) == set()  # type: ignore[arg-type]

    # One attempt, then the retry window holds the rest off.
    assert broken.calls == 1
    assert _RETRY_AFTER_FAILURE_SECONDS > 0


async def test_missing_token_never_calls_impower(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient({9}, None)
    _patch_client(monkeypatch, client)

    class _NoToken:
        impower_api_base = "https://api.example/v2"
        impower_api_token = ""

    cache = ReversedInvoiceCache()
    assert await cache.get(11227, _NoToken()) == set()  # type: ignore[arg-type]
    assert client.calls == 0
