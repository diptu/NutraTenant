"""CRUD for the Tenant entity and its many-to-many link to Organization.

Distinct from app.api.v1.routes.tenants (the pre-existing organization-
bootstrap API, where "tenant_id" means Organization.slug) — see
app.services.tenant_service for the full rationale. Entirely
superuser-gated: this is new platform-grouping infrastructure with no
per-organization-membership semantics defined (yet).
"""

from __future__ import annotations

import uuid

from app.api.v1.dependencies import get_tenant_service, require_superuser
from app.api.v1.schemas.tenant_group import (
    LinkOrganizationRequest,
    TenantGroupCreateRequest,
    TenantGroupOrganizationOut,
    TenantGroupOut,
    TenantGroupUpdateRequest,
)
from app.infrastructure.db.models.user import User
from app.services.tenant_service import TenantService
from fastapi import APIRouter, Depends, Query, status

router = APIRouter(prefix="/tenant-groups", tags=["tenant-groups"])


@router.post("", response_model=TenantGroupOut, status_code=status.HTTP_201_CREATED)
async def create_tenant_group(
    payload: TenantGroupCreateRequest,
    _admin: User = Depends(require_superuser),
    tenant_service: TenantService = Depends(get_tenant_service),
) -> TenantGroupOut:
    tenant = await tenant_service.create(name=payload.name, slug=payload.slug)
    return TenantGroupOut.model_validate(tenant)


@router.get("", response_model=list[TenantGroupOut])
async def list_tenant_groups(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_superuser),
    tenant_service: TenantService = Depends(get_tenant_service),
) -> list[TenantGroupOut]:
    tenants = await tenant_service.list_all(limit=limit, offset=offset)
    return [TenantGroupOut.model_validate(t) for t in tenants]


@router.get("/{tenant_group_id}", response_model=TenantGroupOut)
async def get_tenant_group(
    tenant_group_id: uuid.UUID,
    _admin: User = Depends(require_superuser),
    tenant_service: TenantService = Depends(get_tenant_service),
) -> TenantGroupOut:
    tenant = await tenant_service.get(tenant_group_id)
    return TenantGroupOut.model_validate(tenant)


@router.patch("/{tenant_group_id}", response_model=TenantGroupOut)
async def update_tenant_group(
    tenant_group_id: uuid.UUID,
    payload: TenantGroupUpdateRequest,
    _admin: User = Depends(require_superuser),
    tenant_service: TenantService = Depends(get_tenant_service),
) -> TenantGroupOut:
    tenant = await tenant_service.update(tenant_group_id, name=payload.name, is_active=payload.is_active)
    return TenantGroupOut.model_validate(tenant)


@router.delete("/{tenant_group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_group(
    tenant_group_id: uuid.UUID,
    _admin: User = Depends(require_superuser),
    tenant_service: TenantService = Depends(get_tenant_service),
) -> None:
    await tenant_service.delete(tenant_group_id)


@router.get("/{tenant_group_id}/organizations", response_model=list[TenantGroupOrganizationOut])
async def list_tenant_group_organizations(
    tenant_group_id: uuid.UUID,
    _admin: User = Depends(require_superuser),
    tenant_service: TenantService = Depends(get_tenant_service),
) -> list[TenantGroupOrganizationOut]:
    organizations = await tenant_service.list_organizations(tenant_group_id)
    return [TenantGroupOrganizationOut.model_validate(o) for o in organizations]


@router.post(
    "/{tenant_group_id}/organizations",
    response_model=TenantGroupOrganizationOut,
    status_code=status.HTTP_201_CREATED,
)
async def link_tenant_group_organization(
    tenant_group_id: uuid.UUID,
    payload: LinkOrganizationRequest,
    _admin: User = Depends(require_superuser),
    tenant_service: TenantService = Depends(get_tenant_service),
) -> TenantGroupOrganizationOut:
    link = await tenant_service.link_organization(tenant_group_id, payload.organization_id)
    return TenantGroupOrganizationOut.model_validate(link.organization)


@router.delete(
    "/{tenant_group_id}/organizations/{organization_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unlink_tenant_group_organization(
    tenant_group_id: uuid.UUID,
    organization_id: uuid.UUID,
    _admin: User = Depends(require_superuser),
    tenant_service: TenantService = Depends(get_tenant_service),
) -> None:
    await tenant_service.unlink_organization(tenant_group_id, organization_id)


@router.get("/by-organization/{organization_id}", response_model=list[TenantGroupOut])
async def list_tenant_groups_for_organization(
    organization_id: uuid.UUID,
    _admin: User = Depends(require_superuser),
    tenant_service: TenantService = Depends(get_tenant_service),
) -> list[TenantGroupOut]:
    tenants = await tenant_service.list_tenants_for_organization(organization_id)
    return [TenantGroupOut.model_validate(t) for t in tenants]
