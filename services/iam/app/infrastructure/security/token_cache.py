"""Minimal async key/value-with-TTL cache abstraction.

Two implementations: a real Redis-backed one for the running service, and
an in-memory one used in tests so the suite never needs a live Redis
instance — mirroring how tests/conftest.py already swaps Postgres for an
in-memory SQLite engine rather than requiring a real database.
"""

from __future__ import annotations

import time
from typing import Protocol, cast

from redis.asyncio import Redis


class TokenCache(Protocol):
    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None: ...

    async def get(self, key: str) -> str | None: ...

    async def pop(self, key: str) -> str | None:
        """Atomically read-then-delete — used for single-use values like OAuth state."""
        ...

    async def delete(self, key: str) -> None: ...


class RedisTokenCache:
    """Assumes the Redis client was constructed with `decode_responses=True`
    (see app/api/v1/dependencies.py) — the redis-py stubs can't express that
    statically, hence the casts."""

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        await self._redis.set(key, value, ex=ttl_seconds)

    async def get(self, key: str) -> str | None:
        return cast("str | None", await self._redis.get(key))

    async def pop(self, key: str) -> str | None:
        return cast("str | None", await self._redis.getdel(key))

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)


class InMemoryTokenCache:
    """Process-local fallback — used by tests and any environment without Redis."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float]] = {}

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        self._store[key] = (value, time.monotonic() + ttl_seconds)

    async def get(self, key: str) -> str | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    async def pop(self, key: str) -> str | None:
        value = await self.get(key)
        self._store.pop(key, None)
        return value

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)
