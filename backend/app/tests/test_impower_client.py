import httpx
import pytest

from app.integrations.impower.client import ImpowerClient, ImpowerError


def _slice_response(items: list[dict[str, object]]) -> dict[str, object]:
    return {"content": items, "empty": not items, "size": len(items)}


async def test_bearer_token_is_sent() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=_slice_response([]))

    transport = httpx.MockTransport(handler)
    async with ImpowerClient("https://api.example/v2", "tok123", transport=transport) as client:
        await client.list_properties()

    assert captured["auth"] == "Bearer tok123"


async def test_paginates_until_empty() -> None:
    pages = [
        [{"id": 1, "type": "OWNER", "state": "READY", "name": "P1"}],
        [{"id": 2, "type": "RENTAL", "state": "READY", "name": "P2"}],
        [],
    ]
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "0"))
        call_count["n"] += 1
        return httpx.Response(200, json=_slice_response(pages[page]))

    transport = httpx.MockTransport(handler)
    async with ImpowerClient("https://api.example/v2", "tok", transport=transport) as client:
        collected = [p async for p in client.iter_properties()]

    assert [p.id for p in collected] == [1, 2]
    assert call_count["n"] == 3  # three GETs total: two with content, one empty


async def _noop_sleep(_: float) -> None:
    return None


async def test_retries_on_500_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.impower.client.asyncio.sleep", _noop_sleep)
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503, text="upstream down")
        return httpx.Response(200, json=_slice_response([]))

    transport = httpx.MockTransport(handler)
    async with ImpowerClient("https://api.example/v2", "tok", transport=transport) as client:
        result = await client.list_properties()

    assert attempts["n"] == 3
    assert result.content == []


async def test_raises_after_max_retries_on_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.impower.client.asyncio.sleep", _noop_sleep)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="permanently down")

    transport = httpx.MockTransport(handler)
    async with ImpowerClient("https://api.example/v2", "tok", transport=transport) as client:
        with pytest.raises(ImpowerError, match="503"):
            await client.list_properties()


async def test_respects_retry_after_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("app.integrations.impower.client.asyncio.sleep", fake_sleep)
    attempts = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json=_slice_response([]))

    transport = httpx.MockTransport(handler)
    async with ImpowerClient("https://api.example/v2", "tok", transport=transport) as client:
        await client.list_properties()

    assert sleeps == [2.0]
