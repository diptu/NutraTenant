from __future__ import annotations

from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.groups.exceptions import GroupNotFoundError
from app.modules.groups.models import Group
from app.modules.groups.repositories.interfaces.group_repository import GroupRepository
from app.modules.groups.schemas.commands.update_group_command import UpdateGroupCommand
from app.modules.groups.use_cases._audit import record_group_audit_event
from app.modules.groups.use_cases._hierarchy import validate_parent
from sqlalchemy.ext.asyncio import AsyncSession


class UpdateGroupUseCase:
    def __init__(
        self, session: AsyncSession, groups: GroupRepository, audit_log: AuditLogRepository
    ) -> None:
        self._session = session
        self._groups = groups
        self._audit_log = audit_log

    async def execute(self, command: UpdateGroupCommand) -> Group:
        group = await self._groups.get_by_id(command.group_id)
        if group is None:
            raise GroupNotFoundError(f"No group with id '{command.group_id}'")

        if command.name is not None:
            group.name = command.name
        if command.description is not None:
            group.description = command.description
        if command.type is not None:
            group.type = command.type
        if command.status is not None:
            group.status = command.status
        if command.parent_group_id is not None:
            await validate_parent(
                self._groups, command.parent_group_id, group.organization_id, group_id=group.id
            )
            group.parent_group_id = command.parent_group_id
        if command.attributes is not None:
            group.attributes = command.attributes
        if command.metadata is not None:
            group.extra_metadata = command.metadata
        group.updated_at = datetime.now(UTC)

        await record_group_audit_event(
            self._session, self._audit_log, "group.updated", command.updated_by, group, {}
        )
        return group
