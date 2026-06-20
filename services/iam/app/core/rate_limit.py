"""Fixed-window rate limiting — used for per-email login throttling.

Module-level singleton (`get_rate_limiter()`/`reset_rate_limiter()`) rather
than a FastAPI dependency: it needs to be reachable from both the request
path and test fixtures that want to reset state between tests, mirroring
`app.core.config.get_settings()`'s own lru_cache-singleton shape.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.redis_client import try_build_redis_client


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int = 0


class RateLimiter(Protocol):
    async def hit(
        self, key: str, *, limit: int, window_seconds: int
    ) -> RateLimitResult: ...


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._windows: dict[str, tuple[float, int]] = {}

    async def hit(
        self, key: str, *, limit: int, window_seconds: int
    ) -> RateLimitResult:
        now = time.monotonic()
        window_start, count = self._windows.get(key, (now, 0))
        if now - window_start >= window_seconds:
            window_start, count = now, 0

        count += 1
        self._windows[key] = (window_start, count)

        if count > limit:
            retry_after = max(int(window_seconds - (now - window_start)), 1)
            return RateLimitResult(allowed=False, retry_after_seconds=retry_after)
        return RateLimitResult(allowed=True)


class RedisRateLimiter:
    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def hit(
        self, key: str, *, limit: int, window_seconds: int
    ) -> RateLimitResult:
        full_key = f"ratelimit:{key}"
        count = await self._redis.incr(full_key)
        if count == 1:
            await self._redis.expire(full_key, window_seconds)

        if count > limit:
            ttl = await self._redis.ttl(full_key)
            return RateLimitResult(allowed=False, retry_after_seconds=max(int(ttl), 1))
        return RateLimitResult(allowed=True)


_rate_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        client = try_build_redis_client(get_settings())
        _rate_limiter = (
            RedisRateLimiter(client) if client is not None else InMemoryRateLimiter()
        )
    return _rate_limiter


def reset_rate_limiter() -> None:
    global _rate_limiter
    _rate_limiter = None
