"""Role management — the global (platform-wide) catalog, tenant-scoped custom
roles (Role_API_Specification_Extended.md), and the pre-existing global
role-assignment contract (POST/DELETE .../assignments, GET /assignments/{user_id}).

Authorization is scope-dependent: managing a global role (organization_id is
None) requires superuser; managing a tenant-scoped role requires being that
tenant's owner (or superuser). A role's tenant is resolved from the caller's
*current session* (``session_tenant_id``) for create/list, or from the role
itself for every other mutation — see ``_resolve_target_organization_id``
and ``_ensure_can_manage_role``.
"""

from __future__ import annotations

import uuid

from app.api.v1.dependencies import get_current_tenant_slug, get_current_user, require_superuser
from app.api.v1.roles.requests import (
    AssignRolePermissionsRequest,
    AssignRoleRequest,
    AssignUsersToRoleRequest,
    CloneRoleRequest,
    RemoveRolePermissionsRequest,
    RoleCreateRequest,
    RoleUpdateRequest,
)
from app.api.v1.roles.responses import (
    ActivateRoleResponse,
    AssignRolePermissionsResponse,
    AssignUsersToRoleResponse,
    CloneRoleResponse,
    CreateRoleResponse,
    DeactivateRoleResponse,
    DeleteRoleResponse,
    GetRolePermissionsResponse,
    GetRoleResponse,
    GetRoleUsersResponse,
    ListRolesResponse,
    RemoveRolePermissionsResponse,
    RoleOut,
    RolePermissionItem,
    RoleUserItem,
    UpdateRoleResponse,
    UserRoleOut,
)
from app.modules.organizations.dependencies import get_organization_service
from app.modules.organizations.service import OrganizationService
from app.modules.roles.dependencies import get_role_service
from app.modules.roles.models import Role
from app.modules.roles.service import RoleService
from app.modules.users.models import User
from app.shared.exceptions.base import ForbiddenError
from fastapi import APIRouter, Depends, Query, status

router = APIRouter(prefix="/roles", tags=["roles"])


async def _resolve_target_organization_id(
    tenant_id: str | None,
    session_tenant_id: str | None,
    org_service: OrganizationService,
) -> uuid.UUID | None:
    """Where a *new* role (or a listing) is scoped to: an explicit
    ``tenant_id`` in the request if given (see RoleCreateRequest.tenant_id —
    not restricted to superusers, since a session's tenant context is only
    ever resolved at login time and an owner's session may well predate the
    organization they since created/joined; the *actual* gate is the
    require_owner-or-superuser check the caller applies afterward), else the
    caller's current session tenant, else ``None`` (global — superuser-only,
    enforced by the caller).
    """
    effective = tenant_id or session_tenant_id
    if effective is None:
        return None
    organization = await org_service.get_by_slug(effective)
    return organization.id


async def _ensure_can_manage_role(role: Role, current_user: User, org_service: OrganizationService) -> None:
    if current_user.is_superuser:
        return
    if role.organization_id is None:
        raise ForbiddenError("This action requires administrator privileges")
    await org_service.require_owner(role.organization_id, current_user.id)


async def _to_out(role: Role, role_service: RoleService, org_service: OrganizationService) -> RoleOut:
    tenant_id = None
    if role.organization_id is not None:
        organization = await org_service.get(role.organization_id)
        tenant_id = organization.slug
    permissions_count = await role_service.count_permissions(role.id)
    users_count = await role_service.count_users(role)
    return RoleOut(
        id=role.id,
        tenant_id=tenant_id,
        name=role.name,
        slug=role.code,
        description=role.description,
        is_system=role.is_system,
        is_active=role.is_active,
        priority=role.priority,
        permissions_count=permissions_count,
        users_count=users_count,
        created_by=str(role.created_by) if role.created_by else None,
        updated_by=str(role.updated_by) if role.updated_by else None,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


@router.post("/seed", response_model=list[dict])
async def seed_default_roles(
    _admin: User = Depends(require_superuser),
    role_service: RoleService = Depends(get_role_service),
) -> list[dict]:
    """Idempotent — creates admin/member/guest if missing, otherwise returns
    them as-is. Kept in its pre-spec shape (bare {id,name,code,...} objects,
    not the Common Role Object) — used by every other Postman collection's
    Setup folder and several tests for the global RBAC catalog specifically,
    not part of Role_API_Specification_Extended.md."""
    roles = await role_service.seed_defaults()
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "code": r.code,
            "description": r.description,
            "organization_id": None,
            "is_system": r.is_system,
            "is_active": r.is_active,
        }
        for r in roles
    ]


@router.post("", response_model=CreateRoleResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    payload: RoleCreateRequest,
    current_user: User = Depends(get_current_user),
    session_tenant_id: str | None = Depends(get_current_tenant_slug),
    role_service: RoleService = Depends(get_role_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> CreateRoleResponse:
    organization_id = await _resolve_target_organization_id(payload.tenant_id, session_tenant_id, org_service)
    if organization_id is None:
        if not current_user.is_superuser:
            raise ForbiddenError("This action requires administrator privileges")
    elif not current_user.is_superuser:
        await org_service.require_owner(organization_id, current_user.id)

    role = await role_service.create_role(
        name=payload.name,
        code=payload.slug,
        description=payload.description,
        organization_id=organization_id,
        priority=payload.priority,
        permission_codes=payload.permissions,
        created_by=current_user.id,
    )
    return CreateRoleResponse(role=await _to_out(role, role_service, org_service))


@router.get("", response_model=ListRolesResponse)
async def list_roles(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    search: str | None = Query(default=None),
    is_system: bool | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    tenant_id: str | None = Query(
        default=None,
        description="Override the caller's session tenant — same rationale as "
        "RoleCreateRequest.tenant_id. Requires at least membership in that tenant.",
    ),
    current_user: User = Depends(get_current_user),
    session_tenant_id: str | None = Depends(get_current_tenant_slug),
    role_service: RoleService = Depends(get_role_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> ListRolesResponse:
    """Lists the caller's current tenant's roles, or — for a superuser with
    no active tenant context — the global catalog."""
    organization_id: uuid.UUID | None = None
    effective_tenant_id = tenant_id or session_tenant_id
    if effective_tenant_id is not None:
        organization = await org_service.get_by_slug(effective_tenant_id)
        organization_id = organization.id
        if not current_user.is_superuser:
            await org_service.require_membership(organization_id, current_user.id)
    elif not current_user.is_superuser:
        raise ForbiddenError("This action requires administrator privileges")

    roles, total = await role_service.list_paginated(
        organization_id=organization_id,
        page=page,
        page_size=page_size,
        search=search,
        is_system=is_system,
        is_active=is_active,
    )
    return ListRolesResponse(
        total=total,
        page=page,
        page_size=page_size,
        roles=[await _to_out(r, role_service, org_service) for r in roles],
    )


@router.get("/assignments/{user_id}", response_model=list[UserRoleOut])
async def list_user_roles(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    role_service: RoleService = Depends(get_role_service),
) -> list[UserRoleOut]:
    if not current_user.is_superuser and current_user.id != user_id:
        raise ForbiddenError("You can only view your own role assignments")
    assignments = await role_service.list_user_roles(user_id)
    return [UserRoleOut(user_id=a.user_id, role_id=a.role_id, role_code=a.role.code) for a in assignments]


@router.get("/{role_id}", response_model=GetRoleResponse)
async def get_role(
    role_id: uuid.UUID,
    _current_user: User = Depends(get_current_user),
    role_service: RoleService = Depends(get_role_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> GetRoleResponse:
    role = await role_service.get_any_role(role_id)
    return GetRoleResponse(role=await _to_out(role, role_service, org_service))


@router.put("/{role_id}", response_model=UpdateRoleResponse)
async def update_role(
    role_id: uuid.UUID,
    payload: RoleUpdateRequest,
    current_user: User = Depends(get_current_user),
    role_service: RoleService = Depends(get_role_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> UpdateRoleResponse:
    role = await role_service.get_any_role(role_id)
    await _ensure_can_manage_role(role, current_user, org_service)

    role = await role_service.update_role(
        role_id,
        description=payload.description,
        priority=payload.priority,
        is_active=payload.is_active,
        updated_by=current_user.id,
    )
    return UpdateRoleResponse(role=await _to_out(role, role_service, org_service))


@router.delete("/{role_id}", response_model=DeleteRoleResponse)
async def delete_role(
    role_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    role_service: RoleService = Depends(get_role_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> DeleteRoleResponse:
    role = await role_service.get_any_role(role_id)
    await _ensure_can_manage_role(role, current_user, org_service)
    await role_service.delete_role(role_id)
    return DeleteRoleResponse()


@router.post("/{role_id}/permissions", response_model=AssignRolePermissionsResponse)
async def assign_role_permissions(
    role_id: uuid.UUID,
    payload: AssignRolePermissionsRequest,
    current_user: User = Depends(get_current_user),
    role_service: RoleService = Depends(get_role_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> AssignRolePermissionsResponse:
    role = await role_service.get_any_role(role_id)
    await _ensure_can_manage_role(role, current_user, org_service)

    await role_service.add_permissions(role_id, payload.permissions, assigned_by=current_user.id)
    permissions_count = await role_service.count_permissions(role_id)
    return AssignRolePermissionsResponse(role_id=role_id, permissions_count=permissions_count)


@router.get("/{role_id}/permissions", response_model=GetRolePermissionsResponse)
async def get_role_permissions(
    role_id: uuid.UUID,
    _current_user: User = Depends(get_current_user),
    role_service: RoleService = Depends(get_role_service),
) -> GetRolePermissionsResponse:
    role = await role_service.get_role_with_permissions(role_id)
    return GetRolePermissionsResponse(
        role_id=role_id,
        permissions=[RolePermissionItem(id=p.id, name=p.name) for p in role.permissions],
    )


@router.delete("/{role_id}/permissions", response_model=RemoveRolePermissionsResponse)
async def remove_role_permissions(
    role_id: uuid.UUID,
    payload: RemoveRolePermissionsRequest,
    current_user: User = Depends(get_current_user),
    role_service: RoleService = Depends(get_role_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> RemoveRolePermissionsResponse:
    role = await role_service.get_any_role(role_id)
    await _ensure_can_manage_role(role, current_user, org_service)

    await role_service.remove_permissions_by_code(role_id, payload.permissions)
    return RemoveRolePermissionsResponse()


@router.post("/{role_id}/users", response_model=AssignUsersToRoleResponse)
async def assign_users_to_role(
    role_id: uuid.UUID,
    payload: AssignUsersToRoleRequest,
    current_user: User = Depends(get_current_user),
    role_service: RoleService = Depends(get_role_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> AssignUsersToRoleResponse:
    role = await role_service.get_any_role(role_id)
    await _ensure_can_manage_role(role, current_user, org_service)

    assigned = await role_service.bulk_assign_users(role_id, payload.user_ids, actor_id=current_user.id)
    return AssignUsersToRoleResponse(assigned_users=assigned)


@router.get("/{role_id}/users", response_model=GetRoleUsersResponse)
async def get_role_users(
    role_id: uuid.UUID,
    _current_user: User = Depends(get_current_user),
    role_service: RoleService = Depends(get_role_service),
) -> GetRoleUsersResponse:
    users = await role_service.list_role_users(role_id)
    return GetRoleUsersResponse(
        role_id=role_id,
        total=len(users),
        users=[RoleUserItem(id=u.id, name=u.full_name, email=u.email) for u in users],
    )


@router.post("/{role_id}/clone", response_model=CloneRoleResponse, status_code=status.HTTP_201_CREATED)
async def clone_role(
    role_id: uuid.UUID,
    payload: CloneRoleRequest,
    current_user: User = Depends(get_current_user),
    role_service: RoleService = Depends(get_role_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> CloneRoleResponse:
    role = await role_service.get_any_role(role_id)
    await _ensure_can_manage_role(role, current_user, org_service)

    cloned = await role_service.clone_role(
        role_id, name=payload.name, code=payload.slug, created_by=current_user.id
    )
    return CloneRoleResponse(role=await _to_out(cloned, role_service, org_service))


@router.patch("/{role_id}/activate", response_model=ActivateRoleResponse)
async def activate_role(
    role_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    role_service: RoleService = Depends(get_role_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> ActivateRoleResponse:
    role = await role_service.get_any_role(role_id)
    await _ensure_can_manage_role(role, current_user, org_service)
    await role_service.set_active(role_id, True, updated_by=current_user.id)
    return ActivateRoleResponse()


@router.patch("/{role_id}/deactivate", response_model=DeactivateRoleResponse)
async def deactivate_role(
    role_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    role_service: RoleService = Depends(get_role_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> DeactivateRoleResponse:
    role = await role_service.get_any_role(role_id)
    await _ensure_can_manage_role(role, current_user, org_service)
    await role_service.set_active(role_id, False, updated_by=current_user.id)
    return DeactivateRoleResponse()


@router.post(
    "/{role_id}/assignments",
    response_model=UserRoleOut,
    status_code=status.HTTP_201_CREATED,
)
async def assign_role(
    role_id: uuid.UUID,
    payload: AssignRoleRequest,
    admin: User = Depends(require_superuser),
    role_service: RoleService = Depends(get_role_service),
) -> UserRoleOut:
    """Pre-existing global (platform-wide) role-assignment contract — see
    app.modules.roles.service.RoleService.assign_role. Distinct from
    POST /roles/{role_id}/users above, which is the new spec's tenant-scoped
    org-membership mechanism."""
    assignment = await role_service.assign_role(
        user_id=payload.user_id, role_id=role_id, assigned_by=admin.id
    )
    role = await role_service.get_role(role_id)
    return UserRoleOut(user_id=assignment.user_id, role_id=role_id, role_code=role.code)


@router.delete("/{role_id}/assignments/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_role(
    role_id: uuid.UUID,
    user_id: uuid.UUID,
    _admin: User = Depends(require_superuser),
    role_service: RoleService = Depends(get_role_service),
) -> None:
    await role_service.revoke_role(user_id=user_id, role_id=role_id)
