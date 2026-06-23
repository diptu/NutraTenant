"""Repositories for the three auth-flow token tables — kept as one file,
each is a handful of lines."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.infrastructure.database.base_repository import BaseRepository
from app.modules.auth.models import EmailVerificationToken, PasswordResetToken, RefreshToken
from sqlalchemy import select, update


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    """Persistence access for :class:`RefreshToken` — the durable side of
    Refresh Token Rotation."""

    model = RefreshToken

    async def list_active_for_user(self, user_id: uuid.UUID) -> list[RefreshToken]:
        """Every not-yet-revoked session row for a user, most recently issued
        first. Expiry filtering happens in the caller (AuthService.list_sessions)
        — comparing tz-aware/naive datetimes at the SQL level is inconsistent
        between SQLite (tests) and Postgres, see AuthService._aware."""
        stmt = (
            select(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .order_by(RefreshToken.issued_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def revoke_family(self, family_id: uuid.UUID) -> None:
        """Revoke every still-active token in a rotation chain.

        Called when a token already marked revoked is replayed — the
        strongest available signal that the chain has been stolen, so the
        whole family (not just the replayed token) is killed.
        """
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await self._session.execute(stmt)

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        """Kill every active session — used on password change/reset, since a
        credential change should invalidate sessions started before it."""
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await self._session.execute(stmt)


class PasswordResetTokenRepository(BaseRepository[PasswordResetToken]):
    """Persistence access for :class:`PasswordResetToken`."""

    model = PasswordResetToken

    async def get_by_token_hash(self, token_hash: str) -> PasswordResetToken | None:
        stmt = select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


class EmailVerificationTokenRepository(BaseRepository[EmailVerificationToken]):
    """Persistence access for :class:`EmailVerificationToken`."""

    model = EmailVerificationToken

    async def get_by_token_hash(self, token_hash: str) -> EmailVerificationToken | None:
        stmt = select(EmailVerificationToken).where(EmailVerificationToken.token_hash == token_hash)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
