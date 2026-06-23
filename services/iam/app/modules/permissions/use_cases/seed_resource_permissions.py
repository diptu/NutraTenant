from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.permissions.models import Permission
from app.modules.permissions.repositories.interfaces.permission_repository import (
    PermissionRepository,
)
from app.modules.permissions.schemas.commands.seed_resource_permissions_command import (
    SeedResourcePermissionsCommand,
)
from app.modules.permissions.use_cases._audit import record_permission_audit_event
from sqlalchemy.ext.asyncio import AsyncSession

# The 4 standard actions POST /permissions/seed provisions per named resource
# (see the spec's own example: resources:["user"] -> user:create/read/update/delete).
_STANDARD_ACTIONS: tuple[str, ...] = ("create", "read", "update", "delete")


class SeedResourcePermissionsUseCase:
    """Idempotent: provisions the 4 standard actions for each named
    resource, skipping any (resource, action) pair that already exists."""

    def __init__(
        self, session: AsyncSession, permissions: PermissionRepository, audit_log: AuditLogRepository
    ) -> None:
        self._session = session
        self._permissions = permissions
        self._audit_log = audit_log

    async def execute(self, command: SeedResourcePermissionsCommand) -> list[str]:
        created_codes: list[str] = []
        now = datetime.now(UTC)
        for resource in command.resources:
            for action in _STANDARD_ACTIONS:
                code = f"{resource}:{action}"
                if await self._permissions.get_by_code(code) is not None:
                    continue
                permission = Permission(
                    id=uuid.uuid4(),
                    name=code,
                    code=code,
                    resource=resource,
                    action=action,
                    description=None,
                    is_system=True,
                    status="ACTIVE",
                    created_at=now,
                    updated_at=now,
                )
                self._permissions.add(permission)
                await self._session.flush()
                created_codes.append(code)

        await record_permission_audit_event(
            self._session,
            self._audit_log,
            "permission.seeded",
            command.created_by,
            None,
            {"created_permissions": created_codes},
        )
        return created_codes
