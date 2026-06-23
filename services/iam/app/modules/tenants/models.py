"""Tenant model (table: ``tenants``, migration 0015).

A new, additive grouping entity — distinct from this service's pre-existing
"tenant" vocabulary (``Organization.slug``, used as the ``tenant_id`` claim
on access tokens and throughout login/register/switch-tenant), which is
unchanged by this. An ``Organization`` can belong to several ``Tenant``s,
and a ``Tenant`` can group several ``Organization``s, via
:class:`app.infrastructure.database.associations.OrganizationTenant`
(table: ``organization_tenants``) — a bare membership edge with no
role/permission semantics of its own.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from app.infrastructure.database.base import Base
from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.infrastructure.database.associations import OrganizationTenant
    from app.modules.organizations.models import Organization


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    organization_tenants: Mapped[list[OrganizationTenant]] = relationship(
        back_populates="tenant", lazy="raise"
    )

    @property
    def organizations(self) -> list[Organization]:
        """Flattened view of organization_tenants — requires it to already
        be eager-loaded (it's `lazy="raise"`, same convention as
        Role.permissions)."""
        return [ot.organization for ot in self.organization_tenants]
