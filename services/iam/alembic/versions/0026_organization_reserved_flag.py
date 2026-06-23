"""Organization.is_reserved — a superuser-settable flag protecting an
organization from deletion (and, by extension, freeing its slug for reuse).

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("is_reserved", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("organizations", "is_reserved")
