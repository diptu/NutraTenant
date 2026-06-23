from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.permissions.exceptions import PermissionAlreadyExistsError
from app.modules.permissions.models import Permission
from app.modules.permissions.repositories.interfaces.permission_repository import (
    PermissionRepository,
)
from app.modules.permissions.schemas.commands.create_permission_command import (
    CreatePermissionCommand,
)
from app.modules.permissions.use_cases._audit import record_permission_audit_event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class CreatePermissionUseCase:
    def __init__(
        self, session: AsyncSession, permissions: PermissionRepository, audit_log: AuditLogRepository
    ) -> None:
        self._session = session
        self._permissions = permissions
        self._audit_log = audit_log

    async def execute(self, command: CreatePermissionCommand) -> Permission:
        code = f"{command.resource}:{command.action}"
        if await self._permissions.get_by_code(code) is not None:
            raise PermissionAlreadyExistsError(f"Permission '{code}' already exists")

        now = datetime.now(UTC)
        permission = Permission(
            id=uuid.uuid4(),
            name=code,
            code=code,
            resource=command.resource,
            action=command.action,
            description=command.description,
            organization_id=command.organization_id,
            category=command.category,
            risk_level=command.risk_level,
            is_system=False,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        self._permissions.add(permission)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise PermissionAlreadyExistsError(f"Permission '{code}' already exists") from exc

        await record_permission_audit_event(
            self._session, self._audit_log, "permission.created", command.created_by, permission, {}
        )
        return permission
