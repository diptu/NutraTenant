from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

# Import all models so their tables are registered in Base.metadata.
# NOTE: this only covers the auth/RBAC tables this service currently has
# ORM models for (see app/infrastructure/db/models/__init__.py). The
# `policies` and `resources` tables from migration 0001 have no ORM model
# yet (ABAC policy engine is future scope) — autogenerate against this
# target_metadata would propose dropping them; hand-review any
# `alembic revision --autogenerate` output until those models exist.
import app.infrastructure.db.models  # noqa: F401
from alembic import context
from app.core.config import get_settings
from app.infrastructure.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    url = get_settings().database_url
    if not url:
        msg = "DATABASE_URL is not set. Add it to services/iam/.env before running migrations."
        raise RuntimeError(msg)
    engine = create_async_engine(url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


run_migrations_online()
