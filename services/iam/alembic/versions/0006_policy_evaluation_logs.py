"""Policy evaluation tracing table — high-fidelity PDP decision audit trail.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-20

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "policy_evaluation_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("decision", sa.String(10), nullable=False),
        sa.Column(
            "matched_policies", postgresql.JSONB, nullable=False, server_default="[]"
        ),
        sa.Column(
            "subject_snapshot", postgresql.JSONB, nullable=False, server_default="{}"
        ),
        sa.Column(
            "resource_snapshot", postgresql.JSONB, nullable=False, server_default="{}"
        ),
        sa.Column(
            "context_snapshot", postgresql.JSONB, nullable=False, server_default="{}"
        ),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_policy_evaluation_logs_user_id", "policy_evaluation_logs", ["user_id"]
    )
    op.create_index(
        "ix_policy_evaluation_logs_resource_type",
        "policy_evaluation_logs",
        ["resource_type"],
    )
    op.create_index(
        "ix_policy_evaluation_logs_decision", "policy_evaluation_logs", ["decision"]
    )
    op.create_index(
        "ix_policy_evaluation_logs_evaluated_at",
        "policy_evaluation_logs",
        ["evaluated_at"],
    )


def downgrade() -> None:
    op.drop_table("policy_evaluation_logs")
