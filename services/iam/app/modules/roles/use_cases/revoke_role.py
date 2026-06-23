from __future__ import annotations

from app.audit import AuditLogRepository
from app.modules.roles.exceptions import RoleNotAssignedError
from app.modules.roles.repositories.interfaces.role_repository import (
    RoleRepository,
    UserRoleRepository,
)
from app.modules.roles.schemas.commands.revoke_role_command import RevokeRoleCommand
from app.modules.roles.use_cases._audit import record_role_audit_event
from app.modules.roles.use_cases._lookups import get_global_role
from sqlalchemy.ext.asyncio import AsyncSession


class RevokeRoleUseCase:
    def __init__(
        self,
        session: AsyncSession,
        roles: RoleRepository,
        user_roles: UserRoleRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._session = session
        self._roles = roles
        self._user_roles = user_roles
        self._audit_log = audit_log

    async def execute(self, command: RevokeRoleCommand) -> None:
        role = await get_global_role(self._roles, command.role_id)
        assignment = await self._user_roles.get(command.user_id, command.role_id)
        if assignment is None:
            raise RoleNotAssignedError(f"User does not have the '{role.code}' role")
        await self._user_roles.delete(assignment)
        await record_role_audit_event(
            self._session,
            self._audit_log,
            "rbac.role.revoked",
            command.user_id,
            {"role_code": role.code},
        )
