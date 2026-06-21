"""Refresh tokens remember which tenant the session is bound to.

Lets `AuthService.refresh()` re-resolve role/permissions for the same
organization on every rotation, so a refreshed access token's `tenant_id`/
`role` claims never go stale between the initial login and a later refresh.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-20

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "refresh_tokens",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("refresh_tokens", "organization_id")
