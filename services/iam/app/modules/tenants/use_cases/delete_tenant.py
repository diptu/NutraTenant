from __future__ import annotations

from app.modules.tenants.exceptions import TenantNotFoundError
from app.modules.tenants.repositories.interfaces.tenant_repository import (
    OrganizationTenantRepository,
    TenantRepository,
)
from app.modules.tenants.schemas.commands.delete_tenant_command import DeleteTenantCommand
from sqlalchemy.ext.asyncio import AsyncSession


class DeleteTenantUseCase:
    def __init__(
        self, session: AsyncSession, tenants: TenantRepository, links: OrganizationTenantRepository
    ) -> None:
        self._session = session
        self._tenants = tenants
        self._links = links

    async def execute(self, command: DeleteTenantCommand) -> None:
        tenant = await self._tenants.get_by_id(command.tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"No tenant with id '{command.tenant_id}'")

        # Explicit, not relying on ORM cascade — same reasoning as
        # OrganizationService.delete: OrganizationTenant.tenant_id is a
        # NOT NULL FK with no delete-orphan cascade configured on the
        # relationship, so the unit of work would otherwise try to null it.
        for link in await self._links.list_for_tenant(command.tenant_id):
            await self._links.remove_link(link)
        await self._tenants.delete(tenant)
        await self._session.commit()
