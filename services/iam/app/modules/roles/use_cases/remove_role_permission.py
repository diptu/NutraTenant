from __future__ import annotations

from datetime import UTC, datetime

from app.modules.permissions.exceptions import PermissionNotFoundError
from app.modules.permissions.repositories.interfaces.permission_repository import (
    PermissionRepository,
)
from app.modules.roles.models import Role
from app.modules.roles.repositories.interfaces.role_repository import RoleRepository
from app.modules.roles.schemas.commands.remove_role_permission_command import (
    RemoveRolePermissionCommand,
)
from app.modules.roles.use_cases._lookups import get_any_role, reload_with_permissions
from app.shared.exceptions.base import ForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession


class RemoveRolePermissionUseCase:
    def __init__(
        self, session: AsyncSession, roles: RoleRepository, permissions: PermissionRepository
    ) -> None:
        self._session = session
        self._roles = roles
        self._permissions = permissions

    async def execute(self, command: RemoveRolePermissionCommand) -> Role:
        role = await get_any_role(self._roles, command.role_id)
        if role.is_system:
            raise ForbiddenError("System roles cannot be modified")

        link = await self._permissions.get_role_permission(role.id, command.permission_id)
        if link is None:
            raise PermissionNotFoundError("This role does not have that permission")
        await self._permissions.remove_role_permission(link)

        role.updated_at = datetime.now(UTC)
        await self._session.commit()
        return await reload_with_permissions(self._roles, role.id)
