"""Rate-limit primitive (app/ratelimit.py). Tests the Redis fixed-window
helper directly so coverage doesn't depend on app_env (the FastAPI
dependency is a deliberate no-op in dev)."""

from __future__ import annotations

import uuid
from typing import cast

import pytest
from fastapi import HTTPException
from redis.asyncio import Redis, from_url

from app.config import get_settings
from app.ratelimit import enforce_rate_limit


async def test_enforce_rate_limit_allows_up_to_limit_then_blocks() -> None:
    redis = from_url(get_settings().redis_url, decode_responses=True)  # type: ignore[no-untyped-call]
    key = f"ratelimit:test:{uuid.uuid4()}"
    try:
        # The first `limit` calls in the window are allowed.
        for _ in range(3):
            await enforce_rate_limit(redis, key=key, limit=3, window_seconds=60)
        # The one past the limit is rejected with 429 + Retry-After.
        with pytest.raises(HTTPException) as exc:
            await enforce_rate_limit(redis, key=key, limit=3, window_seconds=60)
        assert exc.value.status_code == 429
        assert exc.value.headers is not None
        assert exc.value.headers.get("Retry-After") == "60"
    finally:
        await redis.delete(key)
        await redis.aclose()


class _BoomRedis:
    """Stand-in whose incr() always raises, to prove the limiter fails open."""

    async def incr(self, name: str) -> int:
        raise RuntimeError("redis down")


async def test_enforce_rate_limit_fails_open_on_redis_error() -> None:
    # A Redis outage must degrade to "no limiting", never to a hard error
    # that would lock everyone out of login.
    boom = cast(Redis, _BoomRedis())
    await enforce_rate_limit(boom, key="irrelevant", limit=1, window_seconds=60)
