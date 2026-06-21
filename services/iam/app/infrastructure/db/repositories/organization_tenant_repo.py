"""Repository for the Organization<->Tenant many-to-many link (table:
organization_tenants)."""

import uuid

from app.infrastructure.db.models.associations import OrganizationTenant
from app.infrastructure.db.repositories.base_repository import BaseRepository
from sqlalchemy import select
from sqlalchemy.orm import selectinload


class OrganizationTenantRepository(BaseRepository[OrganizationTenant]):
    """Persistence access for :class:`OrganizationTenant`."""

    model = OrganizationTenant

    async def get_link(self, organization_id: uuid.UUID, tenant_id: uuid.UUID) -> OrganizationTenant | None:
        stmt = select(OrganizationTenant).where(
            OrganizationTenant.organization_id == organization_id,
            OrganizationTenant.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_organization(self, organization_id: uuid.UUID) -> list[OrganizationTenant]:
        stmt = (
            select(OrganizationTenant)
            .where(OrganizationTenant.organization_id == organization_id)
            .options(selectinload(OrganizationTenant.tenant))
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_tenant(self, tenant_id: uuid.UUID) -> list[OrganizationTenant]:
        stmt = (
            select(OrganizationTenant)
            .where(OrganizationTenant.tenant_id == tenant_id)
            .options(selectinload(OrganizationTenant.organization))
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    def add_link(self, link: OrganizationTenant) -> None:
        self._session.add(link)

    async def remove_link(self, link: OrganizationTenant) -> None:
        await self._session.delete(link)
