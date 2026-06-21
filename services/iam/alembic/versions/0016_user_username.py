"""A real, independently-settable `username` column on users.

Previously `username` was always derived from the email's local part (no
column at all) — see app/services/user_service.py and
app/api/v1/routes/auth.py. POST /api/v1/users now accepts a distinct
username at creation time, so it needs somewhere to actually live.

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-22

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("username", sa.String(length=50), nullable=True))
    op.create_unique_constraint("uq_users_username", "users", ["username"])


def downgrade() -> None:
    op.drop_constraint("uq_users_username", "users", type_="unique")
    op.drop_column("users", "username")
