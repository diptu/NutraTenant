"""Access governance — new access_requests, access_reviews, and
access_approvals tables (User and Access APIs Specification).

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "access_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("requested_roles", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("requested_permissions", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("justification", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="PENDING_APPROVAL"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_access_requests_user_id", "access_requests", ["user_id"])

    op.create_table(
        "access_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("review_scope", sa.String(20), nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("review_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_access_reviews_organization_id", "access_reviews", ["organization_id"])

    op.create_table(
        "access_approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "access_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("access_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="COMPLETED"),
        sa.Column(
            "processed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_access_approvals_access_request_id", "access_approvals", ["access_request_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_access_approvals_access_request_id", table_name="access_approvals")
    op.drop_table("access_approvals")
    op.drop_index("ix_access_reviews_organization_id", table_name="access_reviews")
    op.drop_table("access_reviews")
    op.drop_index("ix_access_requests_user_id", table_name="access_requests")
    op.drop_table("access_requests")
