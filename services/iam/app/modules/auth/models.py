"""Auth-flow persistence: refresh tokens (Refresh Token Rotation), and the
sha256-hashed password-reset / email-verification tokens. All three are
exclusively read/written by app.modules.auth.service.AuthService.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.infrastructure.database.base import Base
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class RefreshToken(Base):
    """Backs Refresh Token Rotation (RTR): each row is one issued refresh
    token (its primary key *is* the JWT's ``jti``). Rotating a token sets
    ``revoked_at`` + ``replaced_by_jti`` on the old row and inserts a new row
    sharing the same ``family_id``. If a token already marked ``revoked_at``
    is presented again, every row in that ``family_id`` is revoked — that's
    the reuse-detection signal (see AuthService.refresh)."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_tokens_family_id", "family_id"),
        Index("ix_refresh_tokens_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_jti: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Which tenant this session is bound to (set once at issuance, carried
    # forward unchanged on every rotation) — lets `refresh()` re-resolve
    # role/permissions fresh from the DB on every rotation instead of the
    # access token's tenant_id/role claims silently going stale after one
    # refresh cycle. NULL for sessions with no tenant context (e.g. a user
    # with zero organizations at login time).
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )

    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PasswordResetToken(Base):
    """Only the sha256 hash of the raw token is ever persisted (see
    app.modules.auth.utils.tokens); the raw token itself exists only in the
    (would-be) delivery email and the HTTP response.

    Note the PK here is a plain autoincrement integer, not a UUID — matching
    what migration 0001 actually created, unlike every other model in this
    service.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EmailVerificationToken(Base):
    """Same shape as PasswordResetToken: only the sha256 hash of the raw
    token is ever persisted (see app.modules.auth.utils.tokens); the raw token
    itself exists only in the (would-be) delivery email and, in debug mode,
    the registration HTTP response."""

    __tablename__ = "email_verification_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
