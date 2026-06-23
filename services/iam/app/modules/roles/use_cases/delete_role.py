from __future__ import annotations

from app.modules.roles.exceptions import RoleInUseError
from app.modules.roles.repositories.interfaces.role_repository import RoleRepository
from app.modules.roles.schemas.commands.delete_role_command import DeleteRoleCommand
from app.modules.roles.use_cases._lookups import get_any_role
from app.shared.exceptions.base import ForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession


class DeleteRoleUseCase:
    def __init__(self, session: AsyncSession, roles: RoleRepository) -> None:
        self._session = session
        self._roles = roles

    async def execute(self, command: DeleteRoleCommand) -> None:
        role = await get_any_role(self._roles, command.role_id)
        if role.is_system:
            raise ForbiddenError("System roles cannot be deleted")
        if await self._roles.is_in_use(command.role_id):
            raise RoleInUseError("This role is still assigned to at least one user")
        await self._roles.delete(role)
        await self._session.commit()
