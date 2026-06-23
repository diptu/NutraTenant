"""Permission catalog enrichment — backs the Permission Management API
(category/risk_level/tenant scoping/system flag/enable-disable status).

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "permissions",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column("permissions", sa.Column("category", sa.String(100), nullable=True))
    op.add_column(
        "permissions",
        sa.Column("risk_level", sa.String(20), nullable=False, server_default="LOW"),
    )
    op.add_column(
        "permissions",
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "permissions",
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
    )
    op.create_index("ix_permissions_organization_id", "permissions", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_permissions_organization_id", table_name="permissions")
    op.drop_column("permissions", "status")
    op.drop_column("permissions", "is_system")
    op.drop_column("permissions", "risk_level")
    op.drop_column("permissions", "category")
    op.drop_column("permissions", "organization_id")
