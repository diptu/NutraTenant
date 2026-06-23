from __future__ import annotations

from datetime import UTC, datetime

from app.modules.roles.models import Role
from app.modules.roles.repositories.interfaces.role_repository import RoleRepository
from app.modules.roles.schemas.commands.update_role_command import UpdateRoleCommand
from app.modules.roles.use_cases._lookups import get_any_role
from app.shared.exceptions.base import ForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession


class UpdateRoleUseCase:
    def __init__(self, session: AsyncSession, roles: RoleRepository) -> None:
        self._session = session
        self._roles = roles

    async def execute(self, command: UpdateRoleCommand) -> Role:
        role = await get_any_role(self._roles, command.role_id)
        if role.is_system:
            raise ForbiddenError("System roles cannot be modified")

        if command.name is not None:
            role.name = command.name
        if command.description is not None:
            role.description = command.description
        if command.priority is not None:
            role.priority = command.priority
        if command.is_active is not None:
            role.is_active = command.is_active
        role.updated_by = command.updated_by
        role.updated_at = datetime.now(UTC)

        await self._session.commit()
        return role
