from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.groups.exceptions import GroupMembershipAlreadyExistsError
from app.modules.groups.models import GroupMembership
from app.modules.groups.repositories.interfaces.group_repository import (
    GroupMembershipRepository,
    GroupRepository,
)
from app.modules.groups.schemas.commands.create_group_membership_command import (
    CreateGroupMembershipCommand,
)
from app.modules.groups.use_cases._audit import record_group_audit_event
from app.modules.groups.use_cases._lookups import get_group_in_org
from app.modules.users.exceptions import UserNotFoundError
from app.modules.users.repositories.sqlalchemy.user_repository import UserRepository
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class CreateGroupMembershipUseCase:
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

    async def execute(self, command: CreateGroupMembershipCommand) -> GroupMembership:
        await get_group_in_org(self._groups, command.group_id, command.organization_id)

        user = await self._users.get_by_id(command.user_id)
        if user is None:
            raise UserNotFoundError(f"No user with id '{command.user_id}'")

        if await self._memberships.get_by_group_and_user(command.group_id, command.user_id) is not None:
            raise GroupMembershipAlreadyExistsError("This user already has a membership for this group")

        now = datetime.now(UTC)
        membership = GroupMembership(
            id=uuid.uuid4(),
            user_id=command.user_id,
            group_id=command.group_id,
            membership_type=command.membership_type,
            role=command.role,
            status="ACTIVE",
            expires_at=command.expires_at,
            attributes=command.attributes,
            created_at=now,
            updated_at=now,
        )
        self._memberships.add(membership)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise GroupMembershipAlreadyExistsError(
                "This user already has a membership for this group"
            ) from exc

        await record_group_audit_event(
            self._session, self._audit_log, "group_membership.created", command.created_by, membership, {}
        )
        return membership
