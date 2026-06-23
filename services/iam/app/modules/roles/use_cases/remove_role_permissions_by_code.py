from __future__ import annotations

from datetime import UTC, datetime

from app.modules.permissions.exceptions import PermissionNotFoundError
from app.modules.permissions.repositories.interfaces.permission_repository import (
    PermissionRepository,
)
from app.modules.roles.models import Role
from app.modules.roles.repositories.interfaces.role_repository import RoleRepository
from app.modules.roles.schemas.commands.remove_role_permissions_by_code_command import (
    RemoveRolePermissionsByCodeCommand,
)
from app.modules.roles.use_cases._lookups import get_any_role, reload_with_permissions
from app.shared.exceptions.base import ForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession


class RemoveRolePermissionsByCodeUseCase:
    """Bulk counterpart to RemoveRolePermissionUseCase, addressed by
    permission *code* instead of id — backs DELETE /roles/{role_id}/permissions.
    Idempotent: a code the role doesn't hold is a no-op, not an error
    (only an unknown code is)."""

    def __init__(
        self, session: AsyncSession, roles: RoleRepository, permissions: PermissionRepository
    ) -> None:
        self._session = session
        self._roles = roles
        self._permissions = permissions

    async def execute(self, command: RemoveRolePermissionsByCodeCommand) -> Role:
        role = await get_any_role(self._roles, command.role_id)
        if role.is_system:
            raise ForbiddenError("System roles cannot be modified")

        for code in command.codes:
            permission = await self._permissions.get_by_code(code)
            if permission is None:
                raise PermissionNotFoundError(f"No permission with code '{code}'")
            link = await self._permissions.get_role_permission(role.id, permission.id)
            if link is not None:
                await self._permissions.remove_role_permission(link)

        role.updated_at = datetime.now(UTC)
        await self._session.commit()
        return await reload_with_permissions(self._roles, role.id)
