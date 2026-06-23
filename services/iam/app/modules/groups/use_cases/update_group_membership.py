from __future__ import annotations

from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.groups.exceptions import GroupMembershipNotFoundError
from app.modules.groups.models import GroupMembership
from app.modules.groups.repositories.interfaces.group_repository import (
    GroupMembershipRepository,
)
from app.modules.groups.schemas.commands.update_group_membership_command import (
    UpdateGroupMembershipCommand,
)
from app.modules.groups.use_cases._audit import record_group_audit_event
from sqlalchemy.ext.asyncio import AsyncSession


class UpdateGroupMembershipUseCase:
    def __init__(
        self, session: AsyncSession, memberships: GroupMembershipRepository, audit_log: AuditLogRepository
    ) -> None:
        self._session = session
        self._memberships = memberships
        self._audit_log = audit_log

    async def execute(self, command: UpdateGroupMembershipCommand) -> GroupMembership:
        membership = await self._memberships.get_by_id(command.membership_id)
        if membership is None:
            raise GroupMembershipNotFoundError(f"No group membership with id '{command.membership_id}'")

        if command.role is not None:
            membership.role = command.role
        if command.status is not None:
            membership.status = command.status
        if command.expires_at is not None:
            membership.expires_at = command.expires_at
        if command.attributes is not None:
            membership.attributes = command.attributes
        membership.updated_at = datetime.now(UTC)

        await record_group_audit_event(
            self._session, self._audit_log, "group_membership.updated", command.updated_by, membership, {}
        )
        return membership
