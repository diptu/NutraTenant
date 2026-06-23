from __future__ import annotations

from app.modules.organizations.exceptions import OrganizationNotFoundError
from app.modules.organizations.repositories.interfaces.organization_repository import (
    OrganizationRepository,
)
from app.modules.organizations.schemas.commands.delete_organization_command import (
    DeleteOrganizationCommand,
)
from app.modules.tenants.repositories.interfaces.tenant_repository import (
    OrganizationTenantRepository,
)
from app.shared.exceptions.base import ForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession


class DeleteOrganizationUseCase:
    def __init__(
        self,
        session: AsyncSession,
        orgs: OrganizationRepository,
        org_tenants: OrganizationTenantRepository,
    ) -> None:
        self._session = session
        self._orgs = orgs
        self._org_tenants = org_tenants

    async def execute(self, command: DeleteOrganizationCommand) -> None:
        org = await self._orgs.get_by_id(command.organization_id)
        if org is None:
            raise OrganizationNotFoundError(f"No organization with id '{command.organization_id}'")
        if org.is_reserved:
            raise ForbiddenError("Reserved organizations cannot be deleted")
        # Explicit, not relying on ORM cascade: Organization.members has no
        # cascade configured (and deleting it would mean loading the whole
        # collection through a `lazy="raise"` relationship just to cascade),
        # so without this the unit of work tries to null the NOT NULL
        # organization_members.organization_id column instead of deleting
        # those rows.
        for membership in await self._orgs.list_members(command.organization_id):
            await self._orgs.remove_membership(membership)
        # Same reasoning for the Tenant many-to-many link (see
        # app.modules.tenants.service) — OrganizationTenant.organization_id
        # is a NOT NULL FK with no delete-orphan cascade configured either.
        for link in await self._org_tenants.list_for_organization(command.organization_id):
            await self._org_tenants.remove_link(link)
        await self._orgs.delete(org)
        await self._session.commit()
