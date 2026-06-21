"""Global role assignment repository (the user_roles table)."""

from __future__ import annotations

import uuid

from app.infrastructure.db.models.user_role import UserRole
from app.infrastructure.db.repositories.base_repository import BaseRepository
from sqlalchemy import select
from sqlalchemy.orm import selectinload


class UserRoleRepository(BaseRepository[UserRole]):
    """Persistence access for :class:`UserRole`."""

    model = UserRole

    async def get(self, user_id: uuid.UUID, role_id: uuid.UUID) -> UserRole | None:
        stmt = select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def has_role(self, user_id: uuid.UUID, role_id: uuid.UUID) -> bool:
        return await self.get(user_id, role_id) is not None

    async def list_for_user(self, user_id: uuid.UUID) -> list[UserRole]:
        stmt = select(UserRole).where(UserRole.user_id == user_id).options(selectinload(UserRole.role))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
