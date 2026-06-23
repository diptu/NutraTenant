from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.groups.models import GroupMembership
from app.modules.groups.repositories.interfaces.group_repository import (
    GroupMembershipRepository,
    GroupRepository,
)
from app.modules.groups.schemas.commands.bulk_add_group_members_command import (
    BulkAddGroupMembersCommand,
)
from app.modules.groups.use_cases._audit import record_group_audit_event
from app.modules.groups.use_cases._lookups import get_group_in_org
from app.modules.users.repositories.sqlalchemy.user_repository import UserRepository
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class BulkAddGroupMembersUseCase:
    """Best-effort bulk add for ``POST /api/v1/user-groups/{group_id}/members``
    — an unknown user id, or a user already a member, is skipped rather
    than aborting the whole batch (mirrors PermissionService.bulk_create).
    Returns the count actually added."""

    def __init__(
        self,
        session: AsyncSession,
        groups: GroupRepository,
        memberships: GroupMembershipRepository,
        users: UserRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._session = session
        self._groups = groups
        self._memberships = memberships
        self._users = users
        self._audit_log = audit_log

    async def execute(self, command: BulkAddGroupMembersCommand) -> int:
        await get_group_in_org(self._groups, command.group_id, command.organization_id)
        added = 0
        now = datetime.now(UTC)
        for user_id in command.user_ids:
            if await self._users.get_by_id(user_id) is None:
                continue
            if await self._memberships.get_by_group_and_user(command.group_id, user_id) is not None:
                continue
            membership = GroupMembership(
                id=uuid.uuid4(),
                user_id=user_id,
                group_id=command.group_id,
                membership_type="DIRECT",
                role="MEMBER",
                status="ACTIVE",
                expires_at=None,
                attributes={},
                created_at=now,
                updated_at=now,
            )
            try:
                async with self._session.begin_nested():
                    self._memberships.add(membership)
                    await self._session.flush()
                added += 1
            except IntegrityError:
                continue

        if added:
            await record_group_audit_event(
                self._session,
                self._audit_log,
                "group_membership.bulk_added",
                command.created_by,
                None,
                {"group_id": str(command.group_id), "added_count": added},
            )
        return added
