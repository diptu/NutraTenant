"""Tenant-level operational config (`settings`), descriptive metadata, and
plan tier on organizations — backs the POST /api/v1/tenants bootstrap API.

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-21

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("plan", sa.String(50), nullable=False, server_default="free"),
    )
    op.add_column(
        "organizations",
        sa.Column("settings", postgresql.JSONB, nullable=False, server_default="{}"),
    )
    op.add_column(
        "organizations",
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("organizations", "metadata")
    op.drop_column("organizations", "settings")
    op.drop_column("organizations", "plan")
