"""Shared "build a Redis client, or don't" helper for the small in-memory/Redis
dual-backend subsystems (rate limiter, token blacklist, permission cache).

Construction failures (malformed REDIS_URL, etc.) degrade to the in-memory
backend rather than crashing the request path — this only protects against
*construction* errors, not runtime connection drops.
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis

from app.core.config import Settings

logger = logging.getLogger(__name__)


def try_build_redis_client(settings: Settings) -> Redis | None:
    try:
        return Redis.from_url(settings.redis_url)
    except Exception:
        logger.warning(
            "Failed to construct Redis client from REDIS_URL; falling back to the "
            "in-memory backend",
            exc_info=True,
        )
        return None
