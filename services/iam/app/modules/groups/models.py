"""Group model — backs the Groups & Group Memberships API (migration 0022).

A tenant-scoped collection of users (``Finance Team``, ...) that can be
nested via ``parent_group_id`` and carries its own ABAC ``attributes`` bag,
independent of any member's own ``users.attributes``. Always belongs to one
organization — unlike Role/Permission, there is no "global group" concept.

Plus GroupMembership: no ``organization_id``/``tenant_id`` column of its
own — a membership's tenant is always its group's tenant
(``Group.organization_id``), so storing it again here would just be a
second copy that could drift. The API layer still accepts/returns
``tenant_id`` (validated against the group, derived in responses) to match
the spec's wire shape — see app.modules.groups.service.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from app.infrastructure.database.base import Base, PortableJSONB
from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.modules.users.models import User


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )

    type: Mapped[str] = mapped_column(String(20), nullable=False, default="CUSTOM")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")

    # NULL = a top-level group. SET NULL on the parent's delete rather than
    # CASCADE: removing a parent shouldn't silently delete every descendant.
    parent_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id", ondelete="SET NULL"), nullable=True
    )

    # ABAC attribute bag (department, clearance_level, region, ...) — distinct
    # from `extra_metadata` below, same split as the spec's own request shape.
    attributes: Mapped[dict] = mapped_column(PortableJSONB, nullable=False, default=dict, server_default="{}")
    # Free-form descriptive metadata (tags, caller-supplied created_by, ...).
    # Mapped to the `metadata` column under a different Python attribute name
    # since `metadata` is reserved on declarative models — same aliasing as
    # Organization.extra_metadata.
    extra_metadata: Mapped[dict] = mapped_column(
        "metadata", PortableJSONB, nullable=False, default=dict, server_default="{}"
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    memberships: Mapped[list[GroupMembership]] = relationship(back_populates="group", lazy="raise")


class GroupMembership(Base):
    __tablename__ = "group_memberships"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_membership"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )

    membership_type: Mapped[str] = mapped_column(String(20), nullable=False, default="DIRECT")
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="MEMBER")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attributes: Mapped[dict] = mapped_column(PortableJSONB, nullable=False, default=dict, server_default="{}")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    group: Mapped[Group] = relationship(back_populates="memberships", lazy="raise")
    user: Mapped[User] = relationship(lazy="raise")
