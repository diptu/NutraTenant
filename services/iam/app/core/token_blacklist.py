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

import time
from typing import Protocol

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.redis_client import try_build_redis_client


class TokenBlacklist(Protocol):
    async def add_jti(self, jti: str, ttl_seconds: int) -> None: ...

    async def contains_jti(self, jti: str) -> bool: ...

    async def set_invalidate_before(
        self, user_id: str, *, timestamp: float, ttl_seconds: int
    ) -> None: ...

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

    async def set_invalidate_before(
        self, user_id: str, *, timestamp: float, ttl_seconds: int
    ) -> None:
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
        await self._redis.set(f"blacklist:jti:{jti}", "1", ex=ttl_seconds)

    async def contains_jti(self, jti: str) -> bool:
        return bool(await self._redis.exists(f"blacklist:jti:{jti}"))

    async def set_invalidate_before(
        self, user_id: str, *, timestamp: float, ttl_seconds: int
    ) -> None:
        await self._redis.set(
            f"blacklist:invalidate_before:{user_id}", str(timestamp), ex=ttl_seconds
        )

    async def get_invalidate_before(self, user_id: str) -> float | None:
        value = await self._redis.get(f"blacklist:invalidate_before:{user_id}")
        return float(value) if value is not None else None


_token_blacklist: TokenBlacklist | None = None


def get_token_blacklist() -> TokenBlacklist:
    global _token_blacklist
    if _token_blacklist is None:
        client = try_build_redis_client(get_settings())
        _token_blacklist = (
            RedisTokenBlacklist(client)
            if client is not None
            else InMemoryTokenBlacklist()
        )
    return _token_blacklist


def reset_token_blacklist() -> None:
    global _token_blacklist
    _token_blacklist = None
