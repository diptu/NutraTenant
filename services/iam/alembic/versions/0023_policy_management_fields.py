"""Policy management enrichment — backs the Policies API (policies_api_spec):
display_name/type/status/priority/tenant scoping/subjects/metadata, and
replaces the singular resource/action/is_active columns with list-based
resource_types/actions plus a status enum.

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("policies", sa.Column("display_name", sa.String(255), nullable=True))
    op.add_column(
        "policies", sa.Column("type", sa.String(20), nullable=False, server_default="ABAC")
    )
    op.add_column(
        "policies", sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE")
    )
    op.add_column(
        "policies", sa.Column("priority", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "policies",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "policies",
        sa.Column("resource_types", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "policies", sa.Column("actions", postgresql.JSONB(), nullable=False, server_default="[]")
    )
    op.add_column(
        "policies", sa.Column("subjects", postgresql.JSONB(), nullable=False, server_default="{}")
    )
    op.add_column(
        "policies", sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}")
    )

    # Data migration: fold the old singular resource/action into the new
    # list columns, and is_active into the new status enum, before the old
    # columns are dropped below.
    op.execute("UPDATE policies SET resource_types = jsonb_build_array(resource)")
    op.execute("UPDATE policies SET actions = jsonb_build_array(action)")
    op.execute(
        "UPDATE policies SET status = CASE WHEN is_active THEN 'ACTIVE' ELSE 'INACTIVE' END"
    )

    op.drop_index("idx_policies_resource", table_name="policies")
    op.drop_index("idx_policies_action", table_name="policies")
    op.drop_column("policies", "resource")
    op.drop_column("policies", "action")
    op.drop_column("policies", "is_active")

    op.create_index("ix_policies_organization_id", "policies", ["organization_id"])
    op.create_index("ix_policies_status", "policies", ["status"])


def downgrade() -> None:
    op.drop_index("ix_policies_status", table_name="policies")
    op.drop_index("ix_policies_organization_id", table_name="policies")

    op.add_column("policies", sa.Column("resource", sa.String(100), nullable=True))
    op.add_column("policies", sa.Column("action", sa.String(100), nullable=True))
    op.add_column(
        "policies", sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true")
    )

    op.execute("UPDATE policies SET resource = resource_types->>0")
    op.execute("UPDATE policies SET action = actions->>0")
    op.execute("UPDATE policies SET is_active = (status IN ('ACTIVE', 'PUBLISHED'))")

    op.alter_column("policies", "resource", nullable=False)
    op.alter_column("policies", "action", nullable=False)

    op.create_index("idx_policies_resource", "policies", ["resource"])
    op.create_index("idx_policies_action", "policies", ["action"])

    op.drop_column("policies", "metadata")
    op.drop_column("policies", "subjects")
    op.drop_column("policies", "actions")
    op.drop_column("policies", "resource_types")
    op.drop_column("policies", "organization_id")
    op.drop_column("policies", "priority")
    op.drop_column("policies", "status")
    op.drop_column("policies", "type")
    op.drop_column("policies", "display_name")
