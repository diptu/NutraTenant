"""Permission catalog repository, including role↔permission association helpers."""

import uuid

from app.infrastructure.db.models.associations import RolePermission
from app.infrastructure.db.models.permission import Permission
from app.infrastructure.db.repositories.base_repository import BaseRepository
from sqlalchemy import select


class PermissionRepository(BaseRepository[Permission]):
    """Persistence access for :class:`Permission` and its role associations."""

    model = Permission

    async def get_by_code(self, code: str) -> Permission | None:
        stmt = select(Permission).where(Permission.code == code)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_role_permission(
        self, role_id: uuid.UUID, permission_id: uuid.UUID
    ) -> RolePermission | None:
        stmt = select(RolePermission).where(
            RolePermission.role_id == role_id,
            RolePermission.permission_id == permission_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    def add_role_permission(self, link: RolePermission) -> None:
        self._session.add(link)

    async def remove_role_permission(self, link: RolePermission) -> None:
        await self._session.delete(link)
