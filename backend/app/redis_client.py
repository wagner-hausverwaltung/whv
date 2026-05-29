from collections.abc import AsyncIterator, Awaitable
from typing import cast

from redis.asyncio import Redis, from_url

_redis: Redis | None = None


def init_redis(redis_url: str) -> None:
    global _redis
    _redis = from_url(redis_url, decode_responses=True)  # type: ignore[no-untyped-call]


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
    _redis = None


async def ping_redis() -> bool:
    if _redis is None:
        return False
    try:
        result = await cast(Awaitable[bool], _redis.ping())
    except Exception:
        return False
    return bool(result)


async def get_redis() -> AsyncIterator[Redis]:
    if _redis is None:
        raise RuntimeError("Redis not initialized — call init_redis first")
    yield _redis


def current_redis() -> Redis | None:
    """The shared client if initialized, else None. Unlike `get_redis` (a
    FastAPI dependency that raises when unset), this lets callers degrade
    gracefully when Redis isn't available — e.g. the rate limiter, which
    fails open rather than locking everyone out during a cache outage."""
    return _redis
