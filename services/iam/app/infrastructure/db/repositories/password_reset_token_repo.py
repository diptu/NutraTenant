"""Password reset token repository."""

from __future__ import annotations

from sqlalchemy import select

from app.infrastructure.db.models.password_reset_token import PasswordResetToken
from app.infrastructure.db.repositories.base_repository import BaseRepository


class PasswordResetTokenRepository(BaseRepository[PasswordResetToken]):
    """Persistence access for :class:`PasswordResetToken`."""

    model = PasswordResetToken

    async def get_by_token_hash(self, token_hash: str) -> PasswordResetToken | None:
        stmt = select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
