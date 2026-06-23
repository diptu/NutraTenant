from __future__ import annotations

from app.modules.permissions.exceptions import PermissionNotFoundError
from app.modules.permissions.repositories.interfaces.permission_repository import (
    PermissionRepository,
)
from app.modules.permissions.schemas.commands.delete_permission_command import (
    DeletePermissionCommand,
)
from app.shared.exceptions.base import ForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession


class DeletePermissionUseCase:
    def __init__(self, session: AsyncSession, permissions: PermissionRepository) -> None:
        self._session = session
        self._permissions = permissions

    async def execute(self, command: DeletePermissionCommand) -> None:
        permission = await self._permissions.get_by_id(command.permission_id)
        if permission is None:
            raise PermissionNotFoundError(f"No permission with id '{command.permission_id}'")
        if permission.is_system:
            raise ForbiddenError("System permissions cannot be deleted")
        await self._permissions.delete(permission)
        await self._session.commit()
