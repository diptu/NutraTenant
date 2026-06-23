"""Organization model — maps onto the pre-existing ``organizations`` table
(migration 0002) — plus the token-based email invitation it issues."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from app.infrastructure.database.base import Base, PortableJSONB
from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.infrastructure.database.associations import (
        OrganizationTenant,
        UserOrganizationRole,
    )
    from app.modules.tenants.models import Tenant


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Protects against deletion (migration 0026) — superuser-settable only
    # (see OrganizationService.update / the PATCH route's extra gate, not
    # the regular owner-or-superuser one). Since the row is never deleted
    # while this is set, its `slug` can never be freed for reuse either —
    # there's no separate mechanism needed for that.
    is_reserved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    # Tenant-level ABAC attribute template — merged into a user's own
    # `attributes` (filling only keys they don't already have) when they
    # join this organization. See OrganizationService.add_member.
    default_attributes: Mapped[dict] = mapped_column(
        PortableJSONB, nullable=False, default=dict, server_default="{}"
    )

    plan: Mapped[str] = mapped_column(String(50), nullable=False, default="free", server_default="free")
    # Operational tenant config (allow_self_signup, mfa_required,
    # session_timeout_minutes, password_policy, ...) — distinct from
    # `default_attributes` above, which is specifically the ABAC template
    # merged into *members'* attribute bags, not tenant-level operational
    # config read by the tenant itself.
    settings: Mapped[dict] = mapped_column(PortableJSONB, nullable=False, default=dict, server_default="{}")
    # Free-form descriptive metadata (industry, region, timezone, ...).
    # Mapped to the `metadata` column under a different Python attribute
    # name since `metadata` is reserved on declarative models (it's
    # SQLAlchemy's own MetaData object).
    extra_metadata: Mapped[dict] = mapped_column(
        "metadata", PortableJSONB, nullable=False, default=dict, server_default="{}"
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    members: Mapped[list[UserOrganizationRole]] = relationship(back_populates="organization", lazy="raise")

    # The many-to-many link to Tenant (see app.modules.tenants.models for why
    # this is a separate concept from the `tenant_id` claim/slug used
    # elsewhere in this codebase).
    organization_tenants: Mapped[list[OrganizationTenant]] = relationship(
        back_populates="organization", lazy="raise"
    )

    @property
    def tenants(self) -> list[Tenant]:
        """Flattened view of organization_tenants — requires it to already
        be eager-loaded (it's `lazy="raise"`, same convention as Role.permissions)."""
        return [ot.tenant for ot in self.organization_tenants]


class OrganizationInvitation(Base):
    """Organization invitation — token-based email invite for a non-member.

    Mirrors PasswordResetToken's shape (only the sha256 hash of the raw token
    is ever persisted — see app.shared.security.invitation_token), but
    scoped to an organization + invitee *email* rather than an existing
    user, since the invitee may not have a ``users`` row yet when the invite
    is created.
    """

    __tablename__ = "organization_invitations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role_code: Mapped[str] = mapped_column(String(100), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
