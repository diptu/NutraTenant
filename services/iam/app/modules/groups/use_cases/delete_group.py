from __future__ import annotations

from app.audit import AuditLogRepository
from app.modules.groups.exceptions import GroupNotFoundError
from app.modules.groups.repositories.interfaces.group_repository import GroupRepository
from app.modules.groups.schemas.commands.delete_group_command import DeleteGroupCommand
from app.modules.groups.use_cases._audit import record_group_audit_event
from sqlalchemy.ext.asyncio import AsyncSession


class DeleteGroupUseCase:
    def __init__(
        self, session: AsyncSession, groups: GroupRepository, audit_log: AuditLogRepository
    ) -> None:
        self._session = session
        self._groups = groups
        self._audit_log = audit_log

    async def execute(self, command: DeleteGroupCommand) -> None:
        group = await self._groups.get_by_id(command.group_id)
        if group is None:
            raise GroupNotFoundError(f"No group with id '{command.group_id}'")
        await self._groups.delete(group)
        await record_group_audit_event(self._session, self._audit_log, "group.deleted", None, group, {})
