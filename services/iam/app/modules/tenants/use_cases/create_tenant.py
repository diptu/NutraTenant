from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.modules.tenants.exceptions import TenantAlreadyExistsError
from app.modules.tenants.models import Tenant
from app.modules.tenants.repositories.interfaces.tenant_repository import TenantRepository
from app.modules.tenants.schemas.commands.create_tenant_command import CreateTenantCommand
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class CreateTenantUseCase:
    def __init__(self, session: AsyncSession, tenants: TenantRepository) -> None:
        self._session = session
        self._tenants = tenants

    async def execute(self, command: CreateTenantCommand) -> Tenant:
        if await self._tenants.get_by_slug(command.slug) is not None:
            raise TenantAlreadyExistsError(f"Tenant slug '{command.slug}' is already taken")

        now = datetime.now(UTC)
        tenant = Tenant(
            id=uuid.uuid4(),
            name=command.name,
            slug=command.slug,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self._tenants.add(tenant)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise TenantAlreadyExistsError(f"Tenant slug '{command.slug}' is already taken") from exc

        await self._session.commit()
        return tenant
