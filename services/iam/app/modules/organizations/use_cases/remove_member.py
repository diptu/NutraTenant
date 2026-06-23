from __future__ import annotations

from app.audit import AuditLogRepository
from app.modules.organizations.exceptions import LastOwnerError
from app.modules.organizations.repositories.interfaces.organization_repository import (
    OrganizationRepository,
)
from app.modules.organizations.schemas.commands.remove_member_command import (
    RemoveMemberCommand,
)
from app.modules.organizations.use_cases._audit import record_organization_audit_event
from app.modules.users.exceptions import UserNotFoundError
from sqlalchemy.ext.asyncio import AsyncSession


class RemoveMemberUseCase:
    def __init__(
        self, session: AsyncSession, orgs: OrganizationRepository, audit_log: AuditLogRepository
    ) -> None:
        self._session = session
        self._orgs = orgs
        self._audit_log = audit_log

    async def execute(self, command: RemoveMemberCommand) -> None:
        membership = await self._orgs.get_membership(command.organization_id, command.user_id)
        if membership is None:
            raise UserNotFoundError("This user is not a member of this organization")
        if membership.role.code == "owner" and await self._orgs.count_owners(command.organization_id) <= 1:
            raise LastOwnerError("Cannot remove the organization's last owner")
        role_code = membership.role.code
        await self._orgs.remove_membership(membership)
        await self._session.flush()
        await record_organization_audit_event(
            self._session,
            self._audit_log,
            "tenant.member_removed",
            command.actor_id,
            {
                "organization_id": str(command.organization_id),
                "user_id": str(command.user_id),
                "role_code": role_code,
            },
        )
