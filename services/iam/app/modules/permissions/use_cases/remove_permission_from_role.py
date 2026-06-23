from __future__ import annotations

from app.audit import AuditLogRepository
from app.modules.permissions.exceptions import PermissionNotFoundError
from app.modules.permissions.repositories.interfaces.permission_repository import (
    PermissionRepository,
)
from app.modules.permissions.schemas.commands.remove_permission_from_role_command import (
    RemovePermissionFromRoleCommand,
)
from app.modules.permissions.use_cases._audit import record_permission_audit_event
from sqlalchemy.ext.asyncio import AsyncSession


class RemovePermissionFromRoleUseCase:
    def __init__(
        self, session: AsyncSession, permissions: PermissionRepository, audit_log: AuditLogRepository
    ) -> None:
        self._session = session
        self._permissions = permissions
        self._audit_log = audit_log

    async def execute(self, command: RemovePermissionFromRoleCommand) -> None:
        permission = await self._permissions.get_by_id(command.permission_id)
        if permission is None:
            raise PermissionNotFoundError(f"No permission with id '{command.permission_id}'")
        link = await self._permissions.get_role_permission(command.role_id, command.permission_id)
        if link is not None:
            await self._permissions.remove_role_permission(link)
        await record_permission_audit_event(
            self._session,
            self._audit_log,
            "permission.removed_from_role",
            None,
            permission,
            {"role_id": str(command.role_id)},
        )
