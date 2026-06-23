from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.infrastructure.database.associations import RolePermission
from app.modules.permissions.exceptions import PermissionNotFoundError
from app.modules.permissions.repositories.interfaces.permission_repository import (
    PermissionRepository,
)
from app.modules.roles.models import Role
from app.modules.roles.repositories.interfaces.role_repository import RoleRepository
from app.modules.roles.schemas.commands.add_role_permissions_command import (
    AddRolePermissionsCommand,
)
from app.modules.roles.use_cases._lookups import get_any_role, reload_with_permissions
from app.shared.exceptions.base import ForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession


class AddRolePermissionsUseCase:
    def __init__(
        self, session: AsyncSession, roles: RoleRepository, permissions: PermissionRepository
    ) -> None:
        self._session = session
        self._roles = roles
        self._permissions = permissions

    async def execute(self, command: AddRolePermissionsCommand) -> Role:
        role = await get_any_role(self._roles, command.role_id)
        if role.is_system:
            raise ForbiddenError("System roles cannot be modified")

        now = datetime.now(UTC)
        for code in command.codes:
            permission = await self._permissions.get_by_code(code)
            if permission is None:
                raise PermissionNotFoundError(f"No permission with code '{code}'")
            link = await self._permissions.get_role_permission(role.id, permission.id)
            if link is None:
                self._permissions.add_role_permission(
                    RolePermission(
                        id=uuid.uuid4(),
                        role_id=role.id,
                        permission_id=permission.id,
                        assigned_by=command.assigned_by,
                        created_at=now,
                    )
                )

        # Bust app.core.cache permission-cache entries keyed on this role.
        role.updated_at = now
        await self._session.commit()
        return await reload_with_permissions(self._roles, role.id)
