"""Per-IP rate limiting for unauthenticated / abuse-prone endpoints
(login, password reset, invite redemption, public ballot links).

Fixed-window counters in Redis (INCR + EXPIRE), keyed on the caller's IP.
We sit behind Caddy, so the real client IP is the left-most entry of
`X-Forwarded-For`; we fall back to the socket peer when the header is
absent (direct dev access).

Two deliberate non-strict behaviours:

* **No-op in dev** (`app_env == "dev"`). The test suite logs in from
  127.0.0.1 hundreds of times in one window; throttling there would make
  the suite flaky. Enforcement is live only on staging/prod.
* **Fail-open** on any Redis error or before Redis is initialised. A cache
  outage degrading to "no rate limiting" is a far better failure mode than
  locking every user out of login.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import cast

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis

from app.config import get_settings
from app.redis_client import current_redis

logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    # Behind Caddy, X-Forwarded-For is "client, proxy1, proxy2…"; the
    # left-most hop is the original caller. It's only spoofable if the
    # backend is directly reachable, but on the compose network only Caddy
    # can reach it, so the left-most value is trustworthy enough to throttle
    # on.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    if request.client is not None:
        return request.client.host
    return "unknown"


async def enforce_rate_limit(
    redis: Redis,
    *,
    key: str,
    limit: int,
    window_seconds: int,
) -> None:
    """Increment the fixed-window counter for `key` and raise HTTP 429 once
    the request count within the window exceeds `limit`. Fails open (returns
    without raising) on any Redis error."""
    try:
        count = await cast("Awaitable[int]", redis.incr(key))
        if count == 1:
            # First hit in this window — start the TTL so the bucket resets.
            await cast("Awaitable[bool]", redis.expire(key, window_seconds))
    except Exception:
        logger.warning("rate-limit check skipped (redis error) for key=%s", key)
        return
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Zu viele Anfragen. Bitte später erneut versuchen.",
            headers={"Retry-After": str(window_seconds)},
        )


def rate_limit(
    bucket: str,
    *,
    limit: int,
    window_seconds: int,
) -> Callable[[Request], Awaitable[None]]:
    """Build a FastAPI dependency that throttles a route to `limit` requests
    per `window_seconds` per client IP. No-op in dev; fail-open when Redis is
    unavailable. `bucket` namespaces the counter so different endpoints don't
    share a window."""

    async def _dependency(request: Request) -> None:
        if get_settings().app_env == "dev":
            return
        redis = current_redis()
        if redis is None:
            return
        key = f"ratelimit:{bucket}:{_client_ip(request)}"
        await enforce_rate_limit(redis, key=key, limit=limit, window_seconds=window_seconds)

    return _dependency
