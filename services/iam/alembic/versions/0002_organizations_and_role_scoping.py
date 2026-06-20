"""Organizations, organization_members, and org-scoped custom roles.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-19

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -----------------------------------------------------------------
    # organizations
    # -----------------------------------------------------------------
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_organizations_slug", "organizations", ["slug"])
    op.create_index("idx_organizations_owner_id", "organizations", ["owner_id"])

    # -----------------------------------------------------------------
    # roles.organization_id (additive — NULL preserves existing global roles)
    # -----------------------------------------------------------------
    op.add_column(
        "roles",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("idx_roles_organization_id", "roles", ["organization_id"])

    # Replace the blanket-unique index on roles.slug with scope-aware
    # partial unique indexes: globally unique among system roles, and
    # unique-per-organization among custom roles.
    op.drop_index("idx_roles_slug", table_name="roles")
    op.create_index("idx_roles_slug", "roles", ["slug"])
    op.create_index(
        "uq_roles_global_slug",
        "roles",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NULL"),
    )
    op.create_index(
        "uq_roles_org_slug",
        "roles",
        ["organization_id", "slug"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NOT NULL"),
    )

    # -----------------------------------------------------------------
    # organization_members
    # -----------------------------------------------------------------
    op.create_table(
        "organization_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "invited_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "organization_id", "user_id", name="uq_organization_member"
        ),
    )
    op.create_index(
        "idx_org_members_organization_id", "organization_members", ["organization_id"]
    )
    op.create_index("idx_org_members_user_id", "organization_members", ["user_id"])
    op.create_index("idx_org_members_role_id", "organization_members", ["role_id"])


def downgrade() -> None:
    op.drop_table("organization_members")
    op.drop_index("uq_roles_org_slug", table_name="roles")
    op.drop_index("uq_roles_global_slug", table_name="roles")
    op.drop_index("idx_roles_slug", table_name="roles")
    op.create_index("idx_roles_slug", "roles", ["slug"], unique=True)
    op.drop_index("idx_roles_organization_id", table_name="roles")
    op.drop_column("roles", "organization_id")
    op.drop_table("organizations")
