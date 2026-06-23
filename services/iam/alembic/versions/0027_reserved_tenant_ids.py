"""Reserved tenant_id blocklist — new reserved_tenant_ids table, seeded
with the platform/system words that can never be claimed as an
Organization.slug (subdomain-per-tenant routing, platform routes, ...).

Revision ID: 0027
Revises: 0026
Create Date: 2026-06-23

"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Common platform/system subdomains + generic reserved words — not
# exhaustive, just a sensible starting blocklist; more can be added via
# POST /api/v1/reserved-tenant-ids at any time.
_SEED_RESERVED_TENANT_IDS: tuple[str, ...] = (
    "admin",
    "api",
    "app",
    "auth",
    "blog",
    "dashboard",
    "dev",
    "docs",
    "ftp",
    "help",
    "mail",
    "root",
    "staging",
    "static",
    "status",
    "support",
    "test",
    "www",
)

_reserved_tenant_ids_table = sa.table(
    "reserved_tenant_ids",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("tenant_id", sa.String),
    sa.column("reason", sa.String),
    sa.column("created_by", postgresql.UUID(as_uuid=True)),
    sa.column("created_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    op.create_table(
        "reserved_tenant_ids",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False, unique=True),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    now = datetime.now(UTC)
    op.bulk_insert(
        _reserved_tenant_ids_table,
        [
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "reason": "system-reserved word",
                "created_by": None,
                "created_at": now,
            }
            for tenant_id in _SEED_RESERVED_TENANT_IDS
        ],
    )


def downgrade() -> None:
    op.drop_table("reserved_tenant_ids")
