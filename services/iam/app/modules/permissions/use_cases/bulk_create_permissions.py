from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.permissions.models import Permission
from app.modules.permissions.repositories.interfaces.permission_repository import (
    PermissionRepository,
)
from app.modules.permissions.schemas.commands.bulk_create_permissions_command import (
    BulkCreatePermissionsCommand,
)
from app.modules.permissions.use_cases._audit import record_permission_audit_event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class BulkCreatePermissionsUseCase:
    """Best-effort: a duplicate resource:action pair (already in the DB,
    or repeated within this same batch) counts toward ``failed`` rather
    than aborting the whole batch. Each insert runs in its own SAVEPOINT
    (``begin_nested``) so one failure only unwinds that one row, not
    every row already created earlier in this loop."""

    def __init__(
        self, session: AsyncSession, permissions: PermissionRepository, audit_log: AuditLogRepository
    ) -> None:
        self._session = session
        self._permissions = permissions
        self._audit_log = audit_log

    async def execute(self, command: BulkCreatePermissionsCommand) -> tuple[int, int]:
        created = 0
        failed = 0
        seen_codes: set[str] = set()
        now = datetime.now(UTC)
        for item in command.items:
            code = f"{item['resource']}:{item['action']}"
            if code in seen_codes or await self._permissions.get_by_code(code) is not None:
                failed += 1
                continue
            seen_codes.add(code)

            permission = Permission(
                id=uuid.uuid4(),
                name=code,
                code=code,
                resource=item["resource"],
                action=item["action"],
                description=item.get("description"),
                organization_id=command.organization_id,
                category=item.get("category"),
                risk_level=item.get("risk_level", "LOW"),
                is_system=False,
                status="ACTIVE",
                created_at=now,
                updated_at=now,
            )
            try:
                async with self._session.begin_nested():
                    self._permissions.add(permission)
                    await self._session.flush()
                created += 1
            except IntegrityError:
                failed += 1

        await record_permission_audit_event(
            self._session,
            self._audit_log,
            "permission.bulk_created",
            command.created_by,
            None,
            {"created": created, "failed": failed},
        )
        return created, failed
