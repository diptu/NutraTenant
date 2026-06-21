"""User model — maps onto the pre-existing ``users`` table (migrations 0001/0003)
plus the additive columns introduced in migration 0004 (``full_name``,
``google_subject``, ``attributes``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from app.infrastructure.db.base import Base
from app.infrastructure.db.types import PortableJSONB
from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.infrastructure.db.models.associations import UserOrganizationRole


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Optional profile fields (migration 0014) — surfaced on GET /users/me.
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # A real, independently-settable handle (migration 0016) — distinct from
    # email's local part, which is still the fallback wherever `username` is
    # rendered for an account that's never set one (see
    # app.services.user_service / app.api.v1.routes.auth).
    username: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)

    # Legacy generic OAuth columns (migration 0001) — kept for back-compat,
    # not written to by the Google-specific flow below.
    oauth_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    oauth_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Google's stable, unique `sub` claim — the actual federation join key.
    google_subject: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)

    # Dynamic ABAC subject attributes (department, clearance, region, ...).
    attributes: Mapped[dict] = mapped_column(PortableJSONB, nullable=False, default=dict, server_default="{}")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Admin-settable lifecycle label (migration 0017) — backs PATCH
    # /users/{id}/status. The single source of truth for display
    # (account_status() just returns it); UserService.set_status is the one
    # place that keeps it and `is_active`/`locked_until` in lockstep, so
    # every other access-gating check in this codebase (get_current_user,
    # AuthService) keeps working unmodified off of `is_active` alone.
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE", server_default="ACTIVE")

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Set on admin-provisioned accounts (a temp password was generated on
    # their behalf, see AuthService.provision_user) — cleared the moment the
    # password is actually changed (change_password/reset_password). Not a
    # general-purpose "status" enum: this is the one concrete, enforceable
    # condition that distinguishes an "INVITED" account from an "ACTIVE" one.
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # TOTP-based MFA. The secret is encrypted at rest (Fernet, see
    # app/infrastructure/security/mfa.py) rather than hashed like a
    # password — verification needs the original value back. Not set
    # (mfa_enabled=False) until a setup/confirm round-trip succeeds.
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # sha256 hashes of one-time recovery codes — consumed (removed from the
    # list) on use, same one-way-hash treatment as a password.
    mfa_recovery_codes: Mapped[list[str]] = mapped_column(
        PortableJSONB, nullable=False, default=list, server_default="[]"
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    org_roles: Mapped[list[UserOrganizationRole]] = relationship(
        back_populates="user",
        lazy="raise",
        foreign_keys="UserOrganizationRole.user_id",
    )
