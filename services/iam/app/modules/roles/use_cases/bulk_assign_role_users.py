from __future__ import annotations

from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.organizations.repositories.sqlalchemy.organization_repository import (
    OrganizationRepository,
)
from app.modules.roles.repositories.interfaces.role_repository import RoleRepository
from app.modules.roles.schemas.commands.bulk_assign_role_users_command import (
    BulkAssignRoleUsersCommand,
)
from app.modules.roles.use_cases._audit import record_role_audit_event
from app.modules.roles.use_cases._lookups import get_any_role
from app.shared.exceptions.base import ForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession


class BulkAssignRoleUsersUseCase:
    """Switches each already-existing org member's role to this one —
    backs POST /roles/{role_id}/users. Global roles aren't supported
    here (use POST /users/{user_id}/roles for those) since there's no
    membership row to repoint. Returns how many users were actually
    updated; a user_id with no membership in this role's organization is
    silently skipped, not an error."""

    def __init__(
        self,
        session: AsyncSession,
        roles: RoleRepository,
        orgs: OrganizationRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._session = session
        self._roles = roles
        self._orgs = orgs
        self._audit_log = audit_log

    async def execute(self, command: BulkAssignRoleUsersCommand) -> int:
        role = await get_any_role(self._roles, command.role_id)
        if role.organization_id is None:
            raise ForbiddenError(
                "Global roles don't support direct user assignment — use POST /users/{user_id}/roles instead"
            )

        assigned = 0
        now = datetime.now(UTC)
        for user_id in command.user_ids:
            membership = await self._orgs.get_membership(role.organization_id, user_id)
            if membership is None:
                continue
            membership.role_id = role.id
            membership.updated_at = now
            assigned += 1

        await record_role_audit_event(
            self._session,
            self._audit_log,
            "rbac.role.bulk_assigned",
            command.actor_id,
            {"role_id": str(command.role_id), "assigned_users": assigned},
        )
        return assigned
