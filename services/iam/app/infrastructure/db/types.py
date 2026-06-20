"""Cross-dialect column types shared by multiple models."""

from __future__ import annotations

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

# JSONB on Postgres (binary-stored, GIN-indexable); plain JSON (TEXT-backed)
# on SQLite, which has no JSONB — this is what lets the in-memory SQLite
# test schema (see tests/conftest.py) compile from the same model metadata
# the real Postgres migrations target.
PortableJSONB = JSONB().with_variant(JSON(), "sqlite")
