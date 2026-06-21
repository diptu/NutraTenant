"""Password reset token — maps onto the pre-existing ``password_reset_tokens``
table (migration 0001). Only the sha256 hash of the raw token is ever
persisted (see app/infrastructure/security/reset_token.py); the raw token
itself exists only in the (would-be) delivery email and the HTTP response.

Note the PK here is a plain autoincrement integer, not a UUID — matching
what migration 0001 actually created, unlike every other model in this service.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.infrastructure.db.base import Base
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
