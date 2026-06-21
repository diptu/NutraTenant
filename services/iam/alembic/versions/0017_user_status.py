"""An explicit, admin-settable lifecycle `status` on users — backs
PATCH /api/v1/users/{user_id}/status.

Existing rows default to ACTIVE (matching their current is_active=True).
Plain string column, not a DB-level enum — same convention as every other
status-like field in this codebase (Role.code, Organization.is_active, ...);
the allowed-value set is enforced at the API boundary (a Pydantic Literal).

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-22

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("status", sa.String(length=30), nullable=False, server_default="ACTIVE"),
    )


def downgrade() -> None:
    op.drop_column("users", "status")
