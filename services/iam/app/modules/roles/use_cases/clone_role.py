from __future__ import annotations

from app.modules.roles.models import Role
from app.modules.roles.repositories.interfaces.role_repository import RoleRepository
from app.modules.roles.schemas.commands.clone_role_command import CloneRoleCommand
from app.modules.roles.schemas.commands.create_role_command import CreateRoleCommand
from app.modules.roles.use_cases._lookups import get_any_role
from app.modules.roles.use_cases.create_role import CreateRoleUseCase


class CloneRoleUseCase:
    """Copies description/priority/organization scope/permission grants
    from the source role into a brand-new one — the source role is left
    untouched."""

    def __init__(self, roles: RoleRepository, create_role_use_case: CreateRoleUseCase) -> None:
        self._roles = roles
        self._create_role_use_case = create_role_use_case

    async def execute(self, command: CloneRoleCommand) -> Role:
        source = await get_any_role(self._roles, command.role_id)
        source_with_permissions = await self._roles.get_with_permissions(command.role_id)
        assert source_with_permissions is not None
        permission_codes = [p.code for p in source_with_permissions.permissions]
        return await self._create_role_use_case.execute(
            CreateRoleCommand(
                name=command.name,
                code=command.code,
                description=source.description,
                organization_id=source.organization_id,
                priority=source.priority,
                permission_codes=permission_codes,
                created_by=command.created_by,
            )
        )
