"""User model — maps onto the pre-existing ``users`` table (migrations 0001/0003)
plus the additive columns introduced in migration 0004 (``full_name``,
``google_subject``, ``attributes``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base
from app.infrastructure.db.types import PortableJSONB

if TYPE_CHECKING:
    from app.infrastructure.db.models.associations import UserOrganizationRole


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Legacy generic OAuth columns (migration 0001) — kept for back-compat,
    # not written to by the Google-specific flow below.
    oauth_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    oauth_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Google's stable, unique `sub` claim — the actual federation join key.
    google_subject: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )

    # Dynamic ABAC subject attributes (department, clearance, region, ...).
    attributes: Mapped[dict] = mapped_column(
        PortableJSONB, nullable=False, default=dict, server_default="{}"
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    org_roles: Mapped[list[UserOrganizationRole]] = relationship(
        back_populates="user",
        lazy="raise",
        foreign_keys="UserOrganizationRole.user_id",
    )
