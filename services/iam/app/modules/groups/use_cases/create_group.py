from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.groups.models import Group
from app.modules.groups.repositories.interfaces.group_repository import GroupRepository
from app.modules.groups.schemas.commands.create_group_command import CreateGroupCommand
from app.modules.groups.use_cases._audit import record_group_audit_event
from app.modules.groups.use_cases._hierarchy import validate_parent
from sqlalchemy.ext.asyncio import AsyncSession


class CreateGroupUseCase:
    def __init__(
        self, session: AsyncSession, groups: GroupRepository, audit_log: AuditLogRepository
    ) -> None:
        self._session = session
        self._groups = groups
        self._audit_log = audit_log

    async def execute(self, command: CreateGroupCommand) -> Group:
        if command.parent_group_id is not None:
            await validate_parent(self._groups, command.parent_group_id, command.organization_id)

        now = datetime.now(UTC)
        group = Group(
            id=uuid.uuid4(),
            name=command.name,
            description=command.description,
            organization_id=command.organization_id,
            type=command.type,
            status="ACTIVE",
            parent_group_id=command.parent_group_id,
            attributes=command.attributes,
            extra_metadata=command.metadata,
            created_by=command.created_by,
            created_at=now,
            updated_at=now,
        )
        self._groups.add(group)
        await self._session.flush()

        await record_group_audit_event(
            self._session, self._audit_log, "group.created", command.created_by, group, {}
        )
        return group
