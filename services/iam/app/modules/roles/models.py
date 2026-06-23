"""Role model — maps onto the pre-existing ``roles`` table (migrations 0001/0002) —
plus the global (non-org-scoped) role assignment table (``user_roles``).

The repository layer addresses roles by ``code``; the already-migrated
column is named ``slug``. Aliasing here avoids a destructive rename
migration purely for a naming preference.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from app.infrastructure.database.base import Base
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.infrastructure.database.associations import RolePermission
    from app.modules.permissions.models import Permission


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # NOT unique (migration 0007 drops the blanket UNIQUE migration 0001 put
    # here): every organization provisions its own "Owner"/"Member" roles
    # using those literal display names, so a global UNIQUE on `name` broke
    # the instant a second organization was created. `code`/slug is the
    # real identity column and is already correctly scoped (see below).
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # NOTE: the DB enforces uniqueness on this column via the partial indexes
    # `uq_roles_global_slug` / `uq_roles_org_slug` from migration 0002 (global
    # roles unique by slug; org-scoped roles unique by (organization_id, slug))
    # rather than a single column-level UNIQUE — not representable as a plain
    # SQLAlchemy UniqueConstraint, so it's intentionally omitted here.
    code: Mapped[str] = mapped_column("slug", String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # NULL = a global/system role; set = a role custom to one organization.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    )

    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Higher = takes precedence in a future role-conflict-resolution policy —
    # purely informational today, no resolution logic reads it yet.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    role_permissions: Mapped[list[RolePermission]] = relationship(back_populates="role", lazy="raise")

    @property
    def permissions(self) -> list[Permission]:
        """Flattened view of role_permissions — requires it to already be
        eager-loaded (it's `lazy="raise"`, same as everywhere else)."""
        return [rp.permission for rp in self.role_permissions]


class UserRole(Base):
    """Global (non-org-scoped) role assignment — maps onto the pre-existing
    ``user_roles`` table (migration 0001). This is the coarse-grained RBAC layer:
    platform-wide roles like Admin/Member/Guest, independent of any organization
    membership (compare app.infrastructure.database.associations.UserOrganizationRole,
    which is tenant-scoped).
    """

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_role"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    role: Mapped[Role] = relationship(lazy="raise")
