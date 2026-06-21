"""Drop the blanket UNIQUE on roles.name.

Migration 0001 made `name` globally unique. Migration 0002 added
org-scoped custom roles, which provision roles literally named "Owner"/
"Member" for *every* organization — the global UNIQUE meant creating a
second organization always failed once it tried to insert its own "Owner"
role. `code` (the `slug` column) is the real identity column and is
already correctly scoped via the partial indexes from migration 0002;
`name` is just a display label and never needed to be unique at all.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-20

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Named per app/infrastructure/db/base.py's explicit naming convention
    # (`uq_%(table_name)s_%(column_0_name)s`), not Postgres' own
    # `<table>_<column>_key` default — that convention applies even though
    # migration 0001 declared this via plain `unique=True`.
    op.drop_constraint("uq_roles_name", "roles", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint("uq_roles_name", "roles", ["name"])
