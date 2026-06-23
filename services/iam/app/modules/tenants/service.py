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

from app.infrastructure.database.associations import OrganizationTenant
from app.modules.organizations.models import Organization
from app.modules.organizations.repositories.sqlalchemy.organization_repository import (
    OrganizationRepository,
)
from app.modules.tenants.exceptions import TenantNotFoundError
from app.modules.tenants.models import Tenant
from app.modules.tenants.repositories.sqlalchemy.tenant_repository import (
    OrganizationTenantRepository,
    TenantRepository,
)
from app.modules.tenants.schemas.commands.create_tenant_command import CreateTenantCommand
from app.modules.tenants.schemas.commands.delete_tenant_command import DeleteTenantCommand
from app.modules.tenants.schemas.commands.link_organization_command import (
    LinkOrganizationCommand,
)
from app.modules.tenants.schemas.commands.unlink_organization_command import (
    UnlinkOrganizationCommand,
)
from app.modules.tenants.schemas.commands.update_tenant_command import UpdateTenantCommand
from app.modules.tenants.use_cases.create_tenant import CreateTenantUseCase
from app.modules.tenants.use_cases.delete_tenant import DeleteTenantUseCase
from app.modules.tenants.use_cases.link_organization import LinkOrganizationUseCase
from app.modules.tenants.use_cases.unlink_organization import UnlinkOrganizationUseCase
from app.modules.tenants.use_cases.update_tenant import UpdateTenantUseCase


class TenantService:
    def __init__(self, session) -> None:
        self._session = session
        self._tenants = TenantRepository(session)
        self._orgs = OrganizationRepository(session)
        self._links = OrganizationTenantRepository(session)
        self._create_use_case = CreateTenantUseCase(session, self._tenants)
        self._update_use_case = UpdateTenantUseCase(session, self._tenants)
        self._delete_use_case = DeleteTenantUseCase(session, self._tenants, self._links)
        self._link_use_case = LinkOrganizationUseCase(session, self._tenants, self._orgs, self._links)
        self._unlink_use_case = UnlinkOrganizationUseCase(session, self._links)

    # -- lifecycle -------------------------------------------------------

    async def create(self, *, name: str, slug: str) -> Tenant:
        return await self._create_use_case.execute(CreateTenantCommand(name=name, slug=slug))

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
        command = UpdateTenantCommand(tenant_id=tenant_id, name=name, is_active=is_active)
        return await self._update_use_case.execute(command)

    async def delete(self, tenant_id: uuid.UUID) -> None:
        await self._delete_use_case.execute(DeleteTenantCommand(tenant_id=tenant_id))

    # -- organization membership -----------------------------------------

    async def link_organization(
        self, tenant_id: uuid.UUID, organization_id: uuid.UUID
    ) -> OrganizationTenant:
        command = LinkOrganizationCommand(tenant_id=tenant_id, organization_id=organization_id)
        return await self._link_use_case.execute(command)

    async def unlink_organization(self, tenant_id: uuid.UUID, organization_id: uuid.UUID) -> None:
        command = UnlinkOrganizationCommand(tenant_id=tenant_id, organization_id=organization_id)
        await self._unlink_use_case.execute(command)

    async def list_organizations(self, tenant_id: uuid.UUID) -> list[Organization]:
        await self.get(tenant_id)
        links = await self._links.list_for_tenant(tenant_id)
        return [link.organization for link in links]

    async def list_tenants_for_organization(self, organization_id: uuid.UUID) -> list[Tenant]:
        links = await self._links.list_for_organization(organization_id)
        return [link.tenant for link in links]
