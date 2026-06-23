from __future__ import annotations

from datetime import UTC, datetime

from app.modules.tenants.exceptions import TenantNotFoundError
from app.modules.tenants.models import Tenant
from app.modules.tenants.repositories.interfaces.tenant_repository import TenantRepository
from app.modules.tenants.schemas.commands.update_tenant_command import UpdateTenantCommand
from sqlalchemy.ext.asyncio import AsyncSession


class UpdateTenantUseCase:
    def __init__(self, session: AsyncSession, tenants: TenantRepository) -> None:
        self._session = session
        self._tenants = tenants

    async def execute(self, command: UpdateTenantCommand) -> Tenant:
        tenant = await self._tenants.get_by_id(command.tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"No tenant with id '{command.tenant_id}'")

        if command.name is not None:
            tenant.name = command.name
        if command.is_active is not None:
            tenant.is_active = command.is_active
        tenant.updated_at = datetime.now(UTC)
        await self._session.commit()
        return tenant
