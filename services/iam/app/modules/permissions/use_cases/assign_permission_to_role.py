from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.infrastructure.database.associations import RolePermission
from app.modules.permissions.exceptions import PermissionNotFoundError
from app.modules.permissions.repositories.interfaces.permission_repository import (
    PermissionRepository,
)
from app.modules.permissions.schemas.commands.assign_permission_to_role_command import (
    AssignPermissionToRoleCommand,
)
from app.modules.permissions.use_cases._audit import record_permission_audit_event
from app.modules.roles.exceptions import RoleNotFoundError
from app.modules.roles.repositories.sqlalchemy.role_repository import RoleRepository
from sqlalchemy.ext.asyncio import AsyncSession


class AssignPermissionToRoleUseCase:
    def __init__(
        self,
        session: AsyncSession,
        permissions: PermissionRepository,
        roles: RoleRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._session = session
        self._permissions = permissions
        self._roles = roles
        self._audit_log = audit_log

    async def execute(self, command: AssignPermissionToRoleCommand) -> None:
        permission = await self._permissions.get_by_id(command.permission_id)
        if permission is None:
            raise PermissionNotFoundError(f"No permission with id '{command.permission_id}'")
        role = await self._roles.get_by_id(command.role_id)
        if role is None:
            raise RoleNotFoundError(f"No role with id '{command.role_id}'")

        existing = await self._permissions.get_role_permission(command.role_id, command.permission_id)
        if existing is None:
            self._permissions.add_role_permission(
                RolePermission(
                    id=uuid.uuid4(),
                    role_id=command.role_id,
                    permission_id=command.permission_id,
                    assigned_by=command.assigned_by,
                    created_at=datetime.now(UTC),
                )
            )
        await record_permission_audit_event(
            self._session,
            self._audit_log,
            "permission.assigned_to_role",
            command.assigned_by,
            permission,
            {"role_id": str(command.role_id)},
        )
