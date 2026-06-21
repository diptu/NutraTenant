"""Repository for direct, org-scoped user permission grants (table:
user_permissions) — see app.infrastructure.db.models.associations.UserPermissionGrant."""

import uuid

from app.infrastructure.db.models.associations import UserPermissionGrant
from app.infrastructure.db.repositories.base_repository import BaseRepository
from sqlalchemy import select
from sqlalchemy.orm import selectinload


class UserPermissionGrantRepository(BaseRepository[UserPermissionGrant]):
    """Persistence access for :class:`UserPermissionGrant`."""

    model = UserPermissionGrant

    async def get_link(
        self, user_id: uuid.UUID, organization_id: uuid.UUID, permission_id: uuid.UUID
    ) -> UserPermissionGrant | None:
        stmt = select(UserPermissionGrant).where(
            UserPermissionGrant.user_id == user_id,
            UserPermissionGrant.organization_id == organization_id,
            UserPermissionGrant.permission_id == permission_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_user_in_organization(
        self, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> list[UserPermissionGrant]:
        stmt = (
            select(UserPermissionGrant)
            .where(
                UserPermissionGrant.user_id == user_id,
                UserPermissionGrant.organization_id == organization_id,
            )
            .options(selectinload(UserPermissionGrant.permission))
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    def add_link(self, link: UserPermissionGrant) -> None:
        self._session.add(link)

    async def remove_link(self, link: UserPermissionGrant) -> None:
        await self._session.delete(link)
