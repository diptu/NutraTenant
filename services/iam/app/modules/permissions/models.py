"""Permission model — maps onto the pre-existing ``permissions`` table (migration 0001),
enriched by migration 0020 for the Permission Management API.

Same ``code`` -> ``slug`` aliasing rationale as :mod:`app.modules.roles.models`.

``code``/``name`` stay globally unique (the original migration 0001 constraint) even
for an org-scoped permission — unlike Role, there's no per-organization partial
unique index here. A simplification: two tenants can't each mint their own
``invoice:approve`` permission with the same resource:action pair. Acceptable for
now since most permissions are expected to come from the shared platform catalog
(see app.core.rbac.PLATFORM_PERMISSIONS / POST /permissions/seed).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.infrastructure.database.base import Base
from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    code: Mapped[str] = mapped_column("slug", String(100), unique=True, nullable=False)
    resource: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # NULL = a global/platform permission; set = custom to one tenant.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    )
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="LOW")
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # ACTIVE | DISABLED — toggled via PATCH .../enable|disable, independent
    # of is_system (a system permission can still be disabled, just not deleted).
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
