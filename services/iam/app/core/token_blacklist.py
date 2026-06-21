"""Access-token revocation — two complementary mechanisms:

- ``add_jti`` / ``contains_jti``: blacklist one specific access token by its
  ``jti`` — used by targeted single-session logout.
- ``set_invalidate_before`` / ``get_invalidate_before``: blacklist *every*
  access token issued to a user before a given timestamp — used by
  password change/reset, which must kill all sessions, not just the one
  making the request.

Module-level singleton (`get_token_blacklist()`/`reset_token_blacklist()`),
same shape as `app.core.rate_limit` and `app.core.config.get_settings()`.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

from app.core.config import get_settings
from app.core.redis_client import try_build_redis_client
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class TokenBlacklist(Protocol):
    async def add_jti(self, jti: str, ttl_seconds: int) -> None: ...

    async def contains_jti(self, jti: str) -> bool: ...

    async def set_invalidate_before(self, user_id: str, *, timestamp: float, ttl_seconds: int) -> None: ...

    async def get_invalidate_before(self, user_id: str) -> float | None: ...


class InMemoryTokenBlacklist:
    def __init__(self) -> None:
        self._jtis: dict[str, float] = {}
        self._invalidate_before: dict[str, tuple[float, float]] = {}

    async def add_jti(self, jti: str, ttl_seconds: int) -> None:
        self._jtis[jti] = time.monotonic() + ttl_seconds

    async def contains_jti(self, jti: str) -> bool:
        expiry = self._jtis.get(jti)
        if expiry is None:
            return False
        if time.monotonic() > expiry:
            del self._jtis[jti]
            return False
        return True

    async def set_invalidate_before(self, user_id: str, *, timestamp: float, ttl_seconds: int) -> None:
        self._invalidate_before[user_id] = (timestamp, time.monotonic() + ttl_seconds)

    async def get_invalidate_before(self, user_id: str) -> float | None:
        entry = self._invalidate_before.get(user_id)
        if entry is None:
            return None
        timestamp, expiry = entry
        if time.monotonic() > expiry:
            del self._invalidate_before[user_id]
            return None
        return timestamp


class RedisTokenBlacklist:
    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def add_jti(self, jti: str, ttl_seconds: int) -> None:
        try:
            await self._redis.set(f"blacklist:jti:{jti}", "1", ex=ttl_seconds)
        except RedisError:
            # Same fail-open reasoning as RedisRateLimiter.hit: an outage in
            # Redis (the blacklist's own backend) must never 500 the request
            # that triggered the revocation (e.g. logout) — the revocation
            # just won't take effect until Redis is back.
            logger.warning("Redis unreachable for token blacklist; revocation not recorded", exc_info=True)

    async def contains_jti(self, jti: str) -> bool:
        try:
            return bool(await self._redis.exists(f"blacklist:jti:{jti}"))
        except RedisError:
            logger.warning("Redis unreachable for token blacklist; allowing request", exc_info=True)
            return False

    async def set_invalidate_before(self, user_id: str, *, timestamp: float, ttl_seconds: int) -> None:
        try:
            await self._redis.set(f"blacklist:invalidate_before:{user_id}", str(timestamp), ex=ttl_seconds)
        except RedisError:
            logger.warning("Redis unreachable for token blacklist; revocation not recorded", exc_info=True)

    async def get_invalidate_before(self, user_id: str) -> float | None:
        try:
            value = await self._redis.get(f"blacklist:invalidate_before:{user_id}")
        except RedisError:
            logger.warning("Redis unreachable for token blacklist; allowing request", exc_info=True)
            return None
        return float(value) if value is not None else None


_token_blacklist: TokenBlacklist | None = None


def get_token_blacklist() -> TokenBlacklist:
    global _token_blacklist
    if _token_blacklist is None:
        client = try_build_redis_client(get_settings())
        _token_blacklist = RedisTokenBlacklist(client) if client is not None else InMemoryTokenBlacklist()
    return _token_blacklist


def reset_token_blacklist() -> None:
    global _token_blacklist
    _token_blacklist = None
