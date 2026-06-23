"""Resolved-permission cache-aside store, used by app.modules.organizations.org_permissions.

Module-level singleton (`get_permission_cache()`/`reset_permission_cache()`),
same shape as app.core.rate_limit / app.core.token_blacklist.
"""

from __future__ import annotations

import time
from typing import Protocol

from app.core.config import get_settings
from app.core.redis_client import try_build_redis_client
from redis.asyncio import Redis


class PermissionCache(Protocol):
    async def get(self, key: str) -> set[str] | None: ...

    async def set(self, key: str, value: set[str], *, ttl_seconds: int) -> None: ...


class InMemoryPermissionCache:
    def __init__(self) -> None:
        self._entries: dict[str, tuple[set[str], float]] = {}

    async def get(self, key: str) -> set[str] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        value, expiry = entry
        if time.monotonic() > expiry:
            del self._entries[key]
            return None
        return value

    async def set(self, key: str, value: set[str], *, ttl_seconds: int) -> None:
        self._entries[key] = (value, time.monotonic() + ttl_seconds)


class RedisPermissionCache:
    _SEPARATOR = "\x1f"  # unit separator — permission codes are "resource:action", never contain it

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def get(self, key: str) -> set[str] | None:
        raw = await self._redis.get(f"permcache:{key}")
        if raw is None:
            return None
        text = raw.decode() if isinstance(raw, bytes) else raw
        return set(text.split(self._SEPARATOR)) if text else set()

    async def set(self, key: str, value: set[str], *, ttl_seconds: int) -> None:
        await self._redis.set(f"permcache:{key}", self._SEPARATOR.join(value), ex=ttl_seconds)


_permission_cache: PermissionCache | None = None


def get_permission_cache() -> PermissionCache:
    global _permission_cache
    if _permission_cache is None:
        client = try_build_redis_client(get_settings())
        _permission_cache = RedisPermissionCache(client) if client is not None else InMemoryPermissionCache()
    return _permission_cache


def reset_permission_cache() -> None:
    global _permission_cache
    _permission_cache = None
