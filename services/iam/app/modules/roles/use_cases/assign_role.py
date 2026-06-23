from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.roles.models import UserRole
from app.modules.roles.repositories.interfaces.role_repository import (
    RoleRepository,
    UserRoleRepository,
)
from app.modules.roles.schemas.commands.assign_role_command import AssignRoleCommand
from app.modules.roles.use_cases._audit import record_role_audit_event
from app.modules.roles.use_cases._lookups import get_global_role
from app.modules.users.exceptions import UserNotFoundError
from app.modules.users.repositories.sqlalchemy.user_repository import UserRepository
from app.shared.exceptions.base import AlreadyExistsError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class AssignRoleUseCase:
    def __init__(
        self,
        session: AsyncSession,
        roles: RoleRepository,
        user_roles: UserRoleRepository,
        users: UserRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._session = session
        self._roles = roles
        self._user_roles = user_roles
        self._users = users
        self._audit_log = audit_log

    async def execute(self, command: AssignRoleCommand) -> UserRole:
        role = await get_global_role(self._roles, command.role_id)
        user = await self._users.get_by_id(command.user_id)
        if user is None:
            raise UserNotFoundError(f"No user with id '{command.user_id}'")
        if await self._user_roles.has_role(command.user_id, command.role_id):
            raise AlreadyExistsError(f"User already has the '{role.code}' role")

        now = datetime.now(UTC)
        assignment = UserRole(
            id=uuid.uuid4(),
            user_id=command.user_id,
            role_id=command.role_id,
            assigned_by=command.assigned_by,
            assigned_at=now,
            created_at=now,
            updated_at=now,
        )
        self._user_roles.add(assignment)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise AlreadyExistsError(f"User already has the '{role.code}' role") from exc

        await record_role_audit_event(
            self._session,
            self._audit_log,
            "rbac.role.assigned",
            command.user_id,
            {
                "role_code": role.code,
                "assigned_by": str(command.assigned_by) if command.assigned_by else None,
            },
        )
        return assignment
