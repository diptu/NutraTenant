from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.infrastructure.database.associations import RolePermission
from app.modules.permissions.exceptions import PermissionNotFoundError
from app.modules.permissions.repositories.interfaces.permission_repository import (
    PermissionRepository,
)
from app.modules.roles.exceptions import RoleAlreadyExistsError
from app.modules.roles.models import Role
from app.modules.roles.repositories.interfaces.role_repository import RoleRepository
from app.modules.roles.schemas.commands.create_role_command import CreateRoleCommand
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class CreateRoleUseCase:
    def __init__(
        self, session: AsyncSession, roles: RoleRepository, permissions: PermissionRepository
    ) -> None:
        self._session = session
        self._roles = roles
        self._permissions = permissions

    async def execute(self, command: CreateRoleCommand) -> Role:
        existing = (
            await self._roles.get_by_code(command.code)
            if command.organization_id is None
            else await self._roles.get_by_code_in_org(command.organization_id, command.code)
        )
        if existing is not None:
            raise RoleAlreadyExistsError(f"A role with code '{command.code}' already exists")

        now = datetime.now(UTC)
        role = Role(
            id=uuid.uuid4(),
            name=command.name,
            code=command.code,
            description=command.description,
            organization_id=command.organization_id,
            is_system=False,
            is_active=True,
            priority=command.priority,
            created_by=command.created_by,
            updated_by=command.created_by,
            created_at=now,
            updated_at=now,
        )
        self._roles.add(role)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise RoleAlreadyExistsError(f"A role with code '{command.code}' already exists") from exc

        for perm_code in command.permission_codes or []:
            permission = await self._permissions.get_by_code(perm_code)
            if permission is None:
                raise PermissionNotFoundError(f"No permission with code '{perm_code}'")
            self._permissions.add_role_permission(
                RolePermission(
                    id=uuid.uuid4(),
                    role_id=role.id,
                    permission_id=permission.id,
                    assigned_by=command.created_by,
                    created_at=now,
                )
            )

        await self._session.commit()
        return role
