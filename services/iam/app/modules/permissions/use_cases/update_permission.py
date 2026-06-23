from __future__ import annotations

from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.permissions.exceptions import PermissionNotFoundError
from app.modules.permissions.models import Permission
from app.modules.permissions.repositories.interfaces.permission_repository import (
    PermissionRepository,
)
from app.modules.permissions.schemas.commands.update_permission_command import (
    UpdatePermissionCommand,
)
from app.modules.permissions.use_cases._audit import record_permission_audit_event
from sqlalchemy.ext.asyncio import AsyncSession


class UpdatePermissionUseCase:
    def __init__(
        self, session: AsyncSession, permissions: PermissionRepository, audit_log: AuditLogRepository
    ) -> None:
        self._session = session
        self._permissions = permissions
        self._audit_log = audit_log

    async def execute(self, command: UpdatePermissionCommand) -> Permission:
        permission = await self._permissions.get_by_id(command.permission_id)
        if permission is None:
            raise PermissionNotFoundError(f"No permission with id '{command.permission_id}'")

        if command.description is not None:
            permission.description = command.description
        if command.category is not None:
            permission.category = command.category
        if command.risk_level is not None:
            permission.risk_level = command.risk_level
        permission.updated_at = datetime.now(UTC)

        await record_permission_audit_event(
            self._session, self._audit_log, "permission.updated", command.updated_by, permission, {}
        )
        return permission
