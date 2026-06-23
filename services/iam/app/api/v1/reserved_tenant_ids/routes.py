"""/api/v1/reserved-tenant-ids — superuser-only management of the
tenant_id blocklist (see app.modules.reserved_tenant_ids.service)."""

from __future__ import annotations

from app.api.v1.dependencies import require_superuser
from app.api.v1.reserved_tenant_ids.requests import ReservedTenantIdCreateRequest
from app.api.v1.reserved_tenant_ids.responses import ReservedTenantIdOut
from app.modules.reserved_tenant_ids.dependencies import get_reserved_tenant_id_service
from app.modules.reserved_tenant_ids.service import ReservedTenantIdService
from app.modules.users.models import User
from fastapi import APIRouter, Depends, status

router = APIRouter(prefix="/reserved-tenant-ids", tags=["reserved-tenant-ids"])


@router.post("", response_model=ReservedTenantIdOut, status_code=status.HTTP_201_CREATED)
async def reserve_tenant_id(
    payload: ReservedTenantIdCreateRequest,
    admin: User = Depends(require_superuser),
    reserved_service: ReservedTenantIdService = Depends(get_reserved_tenant_id_service),
) -> ReservedTenantIdOut:
    entry = await reserved_service.add(
        tenant_id=payload.tenant_id, reason=payload.reason, created_by=admin.id
    )
    return ReservedTenantIdOut.model_validate(entry)


@router.get("", response_model=list[ReservedTenantIdOut])
async def list_reserved_tenant_ids(
    _admin: User = Depends(require_superuser),
    reserved_service: ReservedTenantIdService = Depends(get_reserved_tenant_id_service),
) -> list[ReservedTenantIdOut]:
    entries = await reserved_service.list_all()
    return [ReservedTenantIdOut.model_validate(e) for e in entries]


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unreserve_tenant_id(
    tenant_id: str,
    _admin: User = Depends(require_superuser),
    reserved_service: ReservedTenantIdService = Depends(get_reserved_tenant_id_service),
) -> None:
    await reserved_service.remove(tenant_id)
