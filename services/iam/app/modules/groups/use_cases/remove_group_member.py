from __future__ import annotations

from app.audit import AuditLogRepository
from app.modules.groups.exceptions import GroupMembershipNotFoundError
from app.modules.groups.repositories.interfaces.group_repository import (
    GroupMembershipRepository,
)
from app.modules.groups.schemas.commands.remove_group_member_command import (
    RemoveGroupMemberCommand,
)
from app.modules.groups.use_cases._audit import record_group_audit_event
from sqlalchemy.ext.asyncio import AsyncSession


class RemoveGroupMemberUseCase:
    """``DELETE /api/v1/user-groups/{group_id}/members/{user_id}`` —
    addressed by (group, user) rather than a membership id."""

    def __init__(
        self, session: AsyncSession, memberships: GroupMembershipRepository, audit_log: AuditLogRepository
    ) -> None:
        self._session = session
        self._memberships = memberships
        self._audit_log = audit_log

    async def execute(self, command: RemoveGroupMemberCommand) -> None:
        membership = await self._memberships.get_by_group_and_user(command.group_id, command.user_id)
        if membership is None:
            raise GroupMembershipNotFoundError(
                f"No membership for user '{command.user_id}' in group '{command.group_id}'"
            )
        await self._memberships.delete(membership)
        await record_group_audit_event(
            self._session, self._audit_log, "group_membership.deleted", None, membership, {}
        )
