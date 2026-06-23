from __future__ import annotations

from app.modules.tenants.exceptions import OrganizationTenantLinkNotFoundError
from app.modules.tenants.repositories.interfaces.tenant_repository import (
    OrganizationTenantRepository,
)
from app.modules.tenants.schemas.commands.unlink_organization_command import (
    UnlinkOrganizationCommand,
)
from sqlalchemy.ext.asyncio import AsyncSession


class UnlinkOrganizationUseCase:
    def __init__(self, session: AsyncSession, links: OrganizationTenantRepository) -> None:
        self._session = session
        self._links = links

    async def execute(self, command: UnlinkOrganizationCommand) -> None:
        link = await self._links.get_link(command.organization_id, command.tenant_id)
        if link is None:
            raise OrganizationTenantLinkNotFoundError(
                f"Organization '{command.organization_id}' is not linked to tenant '{command.tenant_id}'"
            )
        await self._links.remove_link(link)
        await self._session.commit()
