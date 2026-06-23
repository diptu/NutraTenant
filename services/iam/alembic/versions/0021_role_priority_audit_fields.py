"""Role priority + created_by/updated_by audit columns — backs the Role
Management API (Role_API_Specification_Extended.md).

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "roles", sa.Column("priority", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "roles",
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "roles",
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("roles", "updated_by")
    op.drop_column("roles", "created_by")
    op.drop_column("roles", "priority")
