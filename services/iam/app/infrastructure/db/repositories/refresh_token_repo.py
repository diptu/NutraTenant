"""Refresh token repository — the durable side of Refresh Token Rotation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import update

from app.infrastructure.db.models.refresh_token import RefreshToken
from app.infrastructure.db.repositories.base_repository import BaseRepository


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    """Persistence access for :class:`RefreshToken`."""

    model = RefreshToken

    async def revoke_family(self, family_id: uuid.UUID) -> None:
        """Revoke every still-active token in a rotation chain.

        Called when a token already marked revoked is replayed — the
        strongest available signal that the chain has been stolen, so the
        whole family (not just the replayed token) is killed.
        """
        stmt = (
            update(RefreshToken)
            .where(
                RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None)
            )
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
