from __future__ import annotations

from datetime import UTC, datetime


def aware(value: datetime) -> datetime:
    """Postgres' ``DateTime(timezone=True)`` round-trips tz-aware; SQLite (tests
    only) round-trips naive. Normalize before comparing against `datetime.now(UTC)`."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
