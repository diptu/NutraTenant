"""Permission Management API — catalog CRUD, bulk/seed creation, role
assignment, usage, lifecycle (enable/disable), and audit history.

Mutating endpoints (create/update/delete/bulk/seed/assign/remove/enable/
disable) are superuser-gated, mirroring how the global role catalog
(app.modules.roles.service) is already gated elsewhere in this service —
the spec's "Critical permissions require ADMIN role" / "Permission
assignments require ADMIN privileges" notes map onto the one privileged
role this codebase has at the platform level. Read endpoints (list/get/
search/roles/usage/audit) are open to any authenticated user.
"""

from __future__ import annotations

import uuid
from typing import cast

from app.api.v1.dependencies import get_current_tenant_slug, get_current_user, require_superuser
from app.api.v1.permissions.requests import (
    AssignPermissionToRoleRequest,
    BulkCreatePermissionsRequest,
    PermissionCreateRequest,
    PermissionUpdateRequest,
    SeedPermissionsRequest,
)
from app.api.v1.permissions.responses import (
    AssignPermissionToRoleResponse,
    AuditEventItem,
    BulkCreatePermissionsResponse,
    CreatePermissionResponse,
    DeletePermissionResponse,
    DisablePermissionResponse,
    EnablePermissionResponse,
    GetPermissionAuditResponse,
    GetPermissionResponse,
    GetPermissionRolesResponse,
    GetPermissionUsageResponse,
    ListPermissionsResponse,
    PermissionOut,
    PermissionRoleItem,
    RemovePermissionFromRoleResponse,
    SearchPermissionsResponse,
    SeedPermissionsResponse,
    UpdatePermissionResponse,
)
from app.modules.organizations.dependencies import get_organization_service
from app.modules.organizations.service import OrganizationService
from app.modules.permissions.dependencies import get_permission_service
from app.modules.permissions.models import Permission
from app.modules.permissions.service import PermissionService
from app.modules.permissions.value_objects import PermissionRiskLevel, PermissionStatus
from app.modules.users.models import User
from fastapi import APIRouter, Depends, Query, status

router = APIRouter(prefix="/permissions", tags=["permissions"])


async def _resolve_creator_organization_id(
    session_tenant_id: str | None, org_service: OrganizationService
) -> uuid.UUID | None:
    """The tenant a newly-created permission belongs to — the caller's
    *current session* tenant, same convention as everywhere else in this
    service. None (a global/platform permission) when the caller has no
    tenant context, e.g. a superuser acting platform-wide."""
    if session_tenant_id is None:
        return None
    organization = await org_service.get_by_slug(session_tenant_id)
    return organization.id


async def _to_out(permission: Permission, org_service: OrganizationService) -> PermissionOut:
    tenant_id = None
    if permission.organization_id is not None:
        organization = await org_service.get(permission.organization_id)
        tenant_id = organization.slug
    return PermissionOut(
        id=permission.id,
        name=permission.name,
        resource=permission.resource,
        action=permission.action,
        description=permission.description,
        category=permission.category,
        risk_level=cast(PermissionRiskLevel, permission.risk_level),
        tenant_id=tenant_id,
        is_system=permission.is_system,
        status=cast(PermissionStatus, permission.status),
        created_at=permission.created_at,
        updated_at=permission.updated_at,
    )


@router.post("", response_model=CreatePermissionResponse, status_code=status.HTTP_201_CREATED)
async def create_permission(
    payload: PermissionCreateRequest,
    admin: User = Depends(require_superuser),
    session_tenant_id: str | None = Depends(get_current_tenant_slug),
    permission_service: PermissionService = Depends(get_permission_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> CreatePermissionResponse:
    organization_id = await _resolve_creator_organization_id(session_tenant_id, org_service)
    permission = await permission_service.create(
        resource=payload.resource,
        action=payload.action,
        description=payload.description,
        category=payload.category,
        risk_level=payload.risk_level,
        organization_id=organization_id,
        created_by=admin.id,
    )
    return CreatePermissionResponse(permission=await _to_out(permission, org_service))


@router.get("", response_model=ListPermissionsResponse)
async def list_permissions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    resource: str | None = Query(default=None),
    action: str | None = Query(default=None),
    category: str | None = Query(default=None),
    status_: str | None = Query(default=None, alias="status"),
    _current_user: User = Depends(get_current_user),
    permission_service: PermissionService = Depends(get_permission_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> ListPermissionsResponse:
    permissions, total = await permission_service.list_paginated(
        page=page,
        page_size=page_size,
        resource=resource,
        action=action,
        category=category,
        status=status_,
    )
    return ListPermissionsResponse(
        total=total,
        page=page,
        page_size=page_size,
        permissions=[await _to_out(p, org_service) for p in permissions],
    )


@router.get("/search", response_model=SearchPermissionsResponse)
async def search_permissions(
    q: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=200),
    _current_user: User = Depends(get_current_user),
    permission_service: PermissionService = Depends(get_permission_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> SearchPermissionsResponse:
    results = await permission_service.search(q, limit=limit)
    return SearchPermissionsResponse(results=[await _to_out(p, org_service) for p in results])


@router.post("/bulk", response_model=BulkCreatePermissionsResponse)
async def bulk_create_permissions(
    payload: BulkCreatePermissionsRequest,
    admin: User = Depends(require_superuser),
    session_tenant_id: str | None = Depends(get_current_tenant_slug),
    permission_service: PermissionService = Depends(get_permission_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> BulkCreatePermissionsResponse:
    organization_id = await _resolve_creator_organization_id(session_tenant_id, org_service)
    created, failed = await permission_service.bulk_create(
        [item.model_dump() for item in payload.permissions],
        organization_id=organization_id,
        created_by=admin.id,
    )
    return BulkCreatePermissionsResponse(created=created, failed=failed)


@router.post("/seed", response_model=SeedPermissionsResponse)
async def seed_resource_permissions(
    payload: SeedPermissionsRequest,
    admin: User = Depends(require_superuser),
    permission_service: PermissionService = Depends(get_permission_service),
) -> SeedPermissionsResponse:
    """Idempotent — provisions the standard create/read/update/delete actions
    for each named resource, skipping any that already exist."""
    created_permissions = await permission_service.seed_resources(payload.resources, created_by=admin.id)
    return SeedPermissionsResponse(created_permissions=created_permissions)


@router.get("/{permission_id}", response_model=GetPermissionResponse)
async def get_permission(
    permission_id: uuid.UUID,
    _current_user: User = Depends(get_current_user),
    permission_service: PermissionService = Depends(get_permission_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> GetPermissionResponse:
    permission = await permission_service.get(permission_id)
    return GetPermissionResponse(permission=await _to_out(permission, org_service))


@router.put("/{permission_id}", response_model=UpdatePermissionResponse)
async def update_permission(
    permission_id: uuid.UUID,
    payload: PermissionUpdateRequest,
    admin: User = Depends(require_superuser),
    permission_service: PermissionService = Depends(get_permission_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> UpdatePermissionResponse:
    permission = await permission_service.update(
        permission_id,
        description=payload.description,
        category=payload.category,
        risk_level=payload.risk_level,
        updated_by=admin.id,
    )
    return UpdatePermissionResponse(permission=await _to_out(permission, org_service))


@router.delete("/{permission_id}", response_model=DeletePermissionResponse)
async def delete_permission(
    permission_id: uuid.UUID,
    _admin: User = Depends(require_superuser),
    permission_service: PermissionService = Depends(get_permission_service),
) -> DeletePermissionResponse:
    await permission_service.delete(permission_id)
    return DeletePermissionResponse()


@router.post("/{permission_id}/roles", response_model=AssignPermissionToRoleResponse)
async def assign_permission_to_role(
    permission_id: uuid.UUID,
    payload: AssignPermissionToRoleRequest,
    admin: User = Depends(require_superuser),
    permission_service: PermissionService = Depends(get_permission_service),
) -> AssignPermissionToRoleResponse:
    await permission_service.assign_to_role(permission_id, payload.role_id, assigned_by=admin.id)
    return AssignPermissionToRoleResponse()


@router.delete("/{permission_id}/roles/{role_id}", response_model=RemovePermissionFromRoleResponse)
async def remove_permission_from_role(
    permission_id: uuid.UUID,
    role_id: uuid.UUID,
    _admin: User = Depends(require_superuser),
    permission_service: PermissionService = Depends(get_permission_service),
) -> RemovePermissionFromRoleResponse:
    await permission_service.remove_from_role(permission_id, role_id)
    return RemovePermissionFromRoleResponse()


@router.get("/{permission_id}/roles", response_model=GetPermissionRolesResponse)
async def get_permission_roles(
    permission_id: uuid.UUID,
    _current_user: User = Depends(get_current_user),
    permission_service: PermissionService = Depends(get_permission_service),
) -> GetPermissionRolesResponse:
    roles = await permission_service.list_roles_for(permission_id)
    return GetPermissionRolesResponse(roles=[PermissionRoleItem(id=r.id, name=r.name) for r in roles])


@router.get("/{permission_id}/usage", response_model=GetPermissionUsageResponse)
async def get_permission_usage(
    permission_id: uuid.UUID,
    _current_user: User = Depends(get_current_user),
    permission_service: PermissionService = Depends(get_permission_service),
) -> GetPermissionUsageResponse:
    usage = await permission_service.get_usage(permission_id)
    return GetPermissionUsageResponse(**usage)


@router.patch("/{permission_id}/enable", response_model=EnablePermissionResponse)
async def enable_permission(
    permission_id: uuid.UUID,
    admin: User = Depends(require_superuser),
    permission_service: PermissionService = Depends(get_permission_service),
) -> EnablePermissionResponse:
    await permission_service.set_status(permission_id, "ACTIVE", actor_id=admin.id)
    return EnablePermissionResponse()


@router.patch("/{permission_id}/disable", response_model=DisablePermissionResponse)
async def disable_permission(
    permission_id: uuid.UUID,
    admin: User = Depends(require_superuser),
    permission_service: PermissionService = Depends(get_permission_service),
) -> DisablePermissionResponse:
    await permission_service.set_status(permission_id, "DISABLED", actor_id=admin.id)
    return DisablePermissionResponse()


@router.get("/{permission_id}/audit", response_model=GetPermissionAuditResponse)
async def get_permission_audit_history(
    permission_id: uuid.UUID,
    _current_user: User = Depends(get_current_user),
    permission_service: PermissionService = Depends(get_permission_service),
) -> GetPermissionAuditResponse:
    rows = await permission_service.get_audit_history(permission_id)
    return GetPermissionAuditResponse(
        events=[AuditEventItem(event=row.event_type, timestamp=row.created_at) for row in rows]
    )
