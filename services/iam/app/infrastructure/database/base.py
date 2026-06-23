"""The declarative base every ORM model extends, plus the one cross-dialect
column type multiple modules' models use.

Tests don't use the engine/session factory in app.infrastructure.database.session
— they build their own SQLite engine (see tests/conftest.py) against the same
`Base.metadata`.
"""

from __future__ import annotations

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

# Explicit naming convention so Alembic autogenerate produces deterministic,
# diff-stable constraint/index names instead of dialect-default ones.
_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    pass


Base.metadata.naming_convention = _NAMING_CONVENTION

# JSONB on Postgres (binary-stored, GIN-indexable); plain JSON (TEXT-backed)
# on SQLite, which has no JSONB — this is what lets the in-memory SQLite
# test schema (see tests/conftest.py) compile from the same model metadata
# the real Postgres migrations target.
PortableJSONB = JSONB().with_variant(JSON(), "sqlite")
