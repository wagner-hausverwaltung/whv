from collections.abc import Awaitable
from typing import cast

from redis.asyncio import Redis, from_url

_redis: Redis | None = None


def init_redis(redis_url: str) -> None:
    global _redis
    _redis = from_url(redis_url, decode_responses=True)


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
