from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.infrastructure.database.associations import OrganizationTenant
from app.modules.organizations.exceptions import OrganizationNotFoundError
from app.modules.organizations.repositories.sqlalchemy.organization_repository import (
    OrganizationRepository,
)
from app.modules.tenants.exceptions import (
    OrganizationTenantLinkAlreadyExistsError,
    TenantNotFoundError,
)
from app.modules.tenants.repositories.interfaces.tenant_repository import (
    OrganizationTenantRepository,
    TenantRepository,
)
from app.modules.tenants.schemas.commands.link_organization_command import (
    LinkOrganizationCommand,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class LinkOrganizationUseCase:
    def __init__(
        self,
        session: AsyncSession,
        tenants: TenantRepository,
        orgs: OrganizationRepository,
        links: OrganizationTenantRepository,
    ) -> None:
        self._session = session
        self._tenants = tenants
        self._orgs = orgs
        self._links = links

    async def execute(self, command: LinkOrganizationCommand) -> OrganizationTenant:
        if await self._tenants.get_by_id(command.tenant_id) is None:
            raise TenantNotFoundError(f"No tenant with id '{command.tenant_id}'")
        organization = await self._orgs.get_by_id(command.organization_id)
        if organization is None:
            raise OrganizationNotFoundError(f"No organization with id '{command.organization_id}'")

        if await self._links.get_link(command.organization_id, command.tenant_id) is not None:
            raise OrganizationTenantLinkAlreadyExistsError(
                f"Organization '{command.organization_id}' is already linked to tenant '{command.tenant_id}'"
            )

        now = datetime.now(UTC)
        link = OrganizationTenant(
            id=uuid.uuid4(),
            organization_id=command.organization_id,
            tenant_id=command.tenant_id,
            created_at=now,
            updated_at=now,
        )
        # Populate the relationship attributes directly from objects already
        # in hand — `organization`/`tenant` are `lazy="raise"`, so leaving
        # them unset would make `link.organization`/`link.tenant` raise on
        # access instead of lazy-loading, for any caller that wants them
        # off the freshly created link without a second fetch.
        link.organization = organization
        self._links.add_link(link)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise OrganizationTenantLinkAlreadyExistsError(
                f"Organization '{command.organization_id}' is already linked to tenant '{command.tenant_id}'"
            ) from exc

        await self._session.commit()
        return link
