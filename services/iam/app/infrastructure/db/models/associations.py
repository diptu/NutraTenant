"""Association models for the RBAC graph.

``UserOrganizationRole`` maps onto the pre-existing ``organization_members``
table (migration 0002) — that table already carries exactly the
organization_id + user_id + role_id shape the repository layer expects, so
no new table is introduced for it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from app.infrastructure.db.base import Base
from sqlalchemy import Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.infrastructure.db.models.organization import Organization
    from app.infrastructure.db.models.permission import Permission
    from app.infrastructure.db.models.role import Role
    from app.infrastructure.db.models.tenant import Tenant
    from app.infrastructure.db.models.user import User


class UserOrganizationRole(Base):
    """A user's single role within one organization (table: organization_members)."""

    __tablename__ = "organization_members"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_organization_member"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped[User] = relationship(back_populates="org_roles", lazy="raise", foreign_keys=[user_id])
    organization: Mapped[Organization] = relationship(back_populates="members", lazy="raise")
    role: Mapped[Role] = relationship(lazy="raise")


class RolePermission(Base):
    """A permission granted to a role (table: role_permissions)."""

    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    role: Mapped[Role] = relationship(back_populates="role_permissions", lazy="raise")
    permission: Mapped[Permission] = relationship(lazy="raise")


class OrganizationTenant(Base):
    """Many-to-many link between Organization and Tenant (table:
    organization_tenants) — an organization can belong to several tenants
    and a tenant can group several organizations. A bare membership edge:
    no role/permission semantics of its own, unlike UserOrganizationRole."""

    __tablename__ = "organization_tenants"
    __table_args__ = (UniqueConstraint("organization_id", "tenant_id", name="uq_organization_tenant"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="organization_tenants", lazy="raise")
    tenant: Mapped[Tenant] = relationship(back_populates="organization_tenants", lazy="raise")


class UserPermissionGrant(Base):
    """A permission granted directly to a user, scoped to one organization
    (table: user_permissions) — independent of their role in that org.
    Backs POST/DELETE /users/{user_id}/permissions.

    Additive only: not currently read by get_member_permissions or
    PolicyEngineService, just stored and merged into the Common User
    Object's `permissions` list (see UserService.get_profile_context)."""

    __tablename__ = "user_permissions"
    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", "permission_id", name="uq_user_permission"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped[User] = relationship(lazy="raise", foreign_keys=[user_id])
    organization: Mapped[Organization] = relationship(lazy="raise")
    permission: Mapped[Permission] = relationship(lazy="raise")
