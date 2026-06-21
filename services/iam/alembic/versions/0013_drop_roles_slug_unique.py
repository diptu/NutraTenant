"""Drop the leftover blanket UNIQUE on roles.slug.

Migration 0001 made `slug` globally unique via plain `unique=True`. Migration
0002 intended to replace that with scope-aware partial unique indexes
(`uq_roles_global_slug` for system roles, `uq_roles_org_slug` per
organization) — but it only dropped/recreated the plain non-unique index
`idx_roles_slug`, never the actual `uq_roles_slug` UNIQUE CONSTRAINT itself
(a separate database object). That leftover blanket constraint silently
breaks every organization after the first one: every org provisions roles
literally slugged "owner"/"admin"/"member"/"viewer" (see
app.services.role_lookup.DEFAULT_ORG_ROLES), so a second organization (or a
global "admin" role colliding with an org's) always 500s on the same
duplicate-slug violation migration 0007 already fixed for `name`.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-21

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_roles_slug", "roles", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint("uq_roles_slug", "roles", ["slug"])
