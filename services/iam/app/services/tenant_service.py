"""Tenant CRUD and its many-to-many membership with Organization.

A `Tenant` here is a new, additive grouping entity — distinct from this
service's pre-existing "tenant" vocabulary (`Organization.slug`, used as
the `tenant_id` claim on access tokens and throughout login/register/
switch-tenant), which this does not change. An organization can belong to
several Tenants, and a Tenant can group several Organizations, via
OrganizationTenant (table: organization_tenants) — a bare membership edge,
no role/permission semantics of its own.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.domain.exceptions import (
    OrganizationNotFoundError,
    OrganizationTenantLinkAlreadyExistsError,
    OrganizationTenantLinkNotFoundError,
    TenantAlreadyExistsError,
    TenantNotFoundError,
)
from app.infrastructure.db.models.associations import OrganizationTenant
from app.infrastructure.db.models.organization import Organization
from app.infrastructure.db.models.tenant import Tenant
from app.infrastructure.db.repositories.organization_repo import OrganizationRepository
from app.infrastructure.db.repositories.organization_tenant_repo import (
    OrganizationTenantRepository,
)
from app.infrastructure.db.repositories.tenant_repo import TenantRepository
from sqlalchemy.exc import IntegrityError


class TenantService:
    def __init__(self, session) -> None:
        self._session = session
        self._tenants = TenantRepository(session)
        self._orgs = OrganizationRepository(session)
        self._links = OrganizationTenantRepository(session)

    # -- lifecycle -------------------------------------------------------

    async def create(self, *, name: str, slug: str) -> Tenant:
        if await self._tenants.get_by_slug(slug) is not None:
            raise TenantAlreadyExistsError(f"Tenant slug '{slug}' is already taken")

        now = datetime.now(UTC)
        tenant = Tenant(
            id=uuid.uuid4(),
            name=name,
            slug=slug,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self._tenants.add(tenant)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise TenantAlreadyExistsError(f"Tenant slug '{slug}' is already taken") from exc

        await self._session.commit()
        return tenant

    async def get(self, tenant_id: uuid.UUID) -> Tenant:
        tenant = await self._tenants.get_by_id(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"No tenant with id '{tenant_id}'")
        return tenant

    async def get_by_slug(self, slug: str) -> Tenant:
        tenant = await self._tenants.get_by_slug(slug)
        if tenant is None:
            raise TenantNotFoundError(f"No tenant '{slug}'")
        return tenant

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[Tenant]:
        return await self._tenants.list_all(limit=limit, offset=offset)

    async def update(
        self, tenant_id: uuid.UUID, *, name: str | None = None, is_active: bool | None = None
    ) -> Tenant:
        tenant = await self.get(tenant_id)
        if name is not None:
            tenant.name = name
        if is_active is not None:
            tenant.is_active = is_active
        tenant.updated_at = datetime.now(UTC)
        await self._session.commit()
        return tenant

    async def delete(self, tenant_id: uuid.UUID) -> None:
        tenant = await self.get(tenant_id)
        # Explicit, not relying on ORM cascade — same reasoning as
        # OrganizationService.delete: OrganizationTenant.tenant_id is a
        # NOT NULL FK with no delete-orphan cascade configured on the
        # relationship, so the unit of work would otherwise try to null it.
        for link in await self._links.list_for_tenant(tenant_id):
            await self._links.remove_link(link)
        await self._tenants.delete(tenant)
        await self._session.commit()

    # -- organization membership -----------------------------------------

    async def link_organization(self, tenant_id: uuid.UUID, organization_id: uuid.UUID) -> OrganizationTenant:
        await self.get(tenant_id)
        organization = await self._orgs.get_by_id(organization_id)
        if organization is None:
            raise OrganizationNotFoundError(f"No organization with id '{organization_id}'")

        if await self._links.get_link(organization_id, tenant_id) is not None:
            raise OrganizationTenantLinkAlreadyExistsError(
                f"Organization '{organization_id}' is already linked to tenant '{tenant_id}'"
            )

        now = datetime.now(UTC)
        link = OrganizationTenant(
            id=uuid.uuid4(),
            organization_id=organization_id,
            tenant_id=tenant_id,
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
                f"Organization '{organization_id}' is already linked to tenant '{tenant_id}'"
            ) from exc

        await self._session.commit()
        return link

    async def unlink_organization(self, tenant_id: uuid.UUID, organization_id: uuid.UUID) -> None:
        link = await self._links.get_link(organization_id, tenant_id)
        if link is None:
            raise OrganizationTenantLinkNotFoundError(
                f"Organization '{organization_id}' is not linked to tenant '{tenant_id}'"
            )
        await self._links.remove_link(link)
        await self._session.commit()

    async def list_organizations(self, tenant_id: uuid.UUID) -> list[Organization]:
        await self.get(tenant_id)
        links = await self._links.list_for_tenant(tenant_id)
        return [link.organization for link in links]

    async def list_tenants_for_organization(self, organization_id: uuid.UUID) -> list[Tenant]:
        links = await self._links.list_for_organization(organization_id)
        return [link.tenant for link in links]
