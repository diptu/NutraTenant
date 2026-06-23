"""User display/locale preferences — backs GET/PUT /api/v1/user-profiles/me
(User Domain API Specification).

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("timezone", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("locale", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "locale")
    op.drop_column("users", "timezone")
