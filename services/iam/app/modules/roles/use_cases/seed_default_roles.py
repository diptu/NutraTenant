from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.modules.roles.models import Role
from app.modules.roles.repositories.interfaces.role_repository import RoleRepository
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_GLOBAL_ROLES = (
    ("admin", "Admin", "Platform-wide administrator"),
    ("member", "Member", "Standard platform member"),
    ("guest", "Guest", "Limited, read-mostly access"),
)


class SeedDefaultRolesUseCase:
    """Idempotent — safe to call on every app startup or test setup."""

    def __init__(self, session: AsyncSession, roles: RoleRepository) -> None:
        self._session = session
        self._roles = roles

    async def execute(self) -> list[Role]:
        roles = []
        now = datetime.now(UTC)
        for code, name, description in DEFAULT_GLOBAL_ROLES:
            role = await self._roles.get_by_code(code)
            if role is None:
                role = Role(
                    id=uuid.uuid4(),
                    name=name,
                    code=code,
                    description=description,
                    organization_id=None,
                    is_system=True,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                self._roles.add(role)
            roles.append(role)
        await self._session.commit()
        return roles
