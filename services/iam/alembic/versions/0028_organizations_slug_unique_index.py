"""organizations.slug — drop the redundant plain index.

Migration 0002 declared ``slug`` with ``unique=True`` (which Postgres backs
with an implicit unique index, e.g. ``organizations_slug_key``) *and* a
separate non-unique ``idx_organizations_slug`` index on the same column —
duplicate index bloat (slower writes, no read benefit) rather than an
intentional second access path. This drops the redundant one, leaving the
unique-constraint-backed index as the sole (and now clearly "unique
indexed") index on the column.

Revision ID: 0028
Revises: 0027
Create Date: 2026-06-23

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("idx_organizations_slug", table_name="organizations")


def downgrade() -> None:
    op.create_index("idx_organizations_slug", "organizations", ["slug"])
