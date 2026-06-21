"""Role management — the global (platform-wide) catalog and org-scoped custom roles.

Authorization is scope-dependent: managing a global role (organization_id is
None) requires superuser; managing an org-scoped role requires being that
organization's owner (or superuser). Because that depends on the *role's*
scope rather than a fixed dependency, it's checked inline rather than via a
single `Depends(...)` guard.
"""

from __future__ import annotations

import uuid

from app.api.v1.dependencies import (
    get_current_user,
    get_organization_service,
    get_role_service,
    require_superuser,
)
from app.api.v1.schemas.role import (
    AddRolePermissionsRequest,
    AssignRoleRequest,
    RoleCreateRequest,
    RoleOut,
    RoleUpdateRequest,
    RoleWithPermissionsOut,
    UserRoleOut,
)
from app.domain.exceptions import ForbiddenError
from app.infrastructure.db.models.role import Role
from app.infrastructure.db.models.user import User
from app.services.organization_service import OrganizationService
from app.services.role_service import RoleService
from fastapi import APIRouter, Depends, status

router = APIRouter(prefix="/roles", tags=["roles"])


async def _ensure_can_manage_role(role: Role, current_user: User, org_service: OrganizationService) -> None:
    if current_user.is_superuser:
        return
    if role.organization_id is None:
        raise ForbiddenError("This action requires administrator privileges")
    await org_service.require_owner(role.organization_id, current_user.id)


@router.post("/seed", response_model=list[RoleOut])
async def seed_default_roles(
    _admin: User = Depends(require_superuser),
    role_service: RoleService = Depends(get_role_service),
) -> list[RoleOut]:
    """Idempotent — creates admin/member/guest if missing, otherwise returns them as-is."""
    roles = await role_service.seed_defaults()
    return [RoleOut.model_validate(r) for r in roles]


@router.get("", response_model=list[RoleOut])
async def list_roles(
    _current_user: User = Depends(get_current_user),
    role_service: RoleService = Depends(get_role_service),
) -> list[RoleOut]:
    roles = await role_service.list_roles()
    return [RoleOut.model_validate(r) for r in roles]


@router.post("", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(
    payload: RoleCreateRequest,
    current_user: User = Depends(get_current_user),
    role_service: RoleService = Depends(get_role_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> RoleOut:
    if payload.organization_id is None:
        if not current_user.is_superuser:
            raise ForbiddenError("This action requires administrator privileges")
    elif not current_user.is_superuser:
        await org_service.require_owner(payload.organization_id, current_user.id)

    role = await role_service.create_role(
        name=payload.name,
        code=payload.code,
        description=payload.description,
        organization_id=payload.organization_id,
    )
    return RoleOut.model_validate(role)


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


@router.get("/{role_id}", response_model=RoleOut)
async def get_role(
    role_id: uuid.UUID,
    _current_user: User = Depends(get_current_user),
    role_service: RoleService = Depends(get_role_service),
) -> RoleOut:
    role = await role_service.get_any_role(role_id)
    return RoleOut.model_validate(role)


@router.patch("/{role_id}", response_model=RoleOut)
async def update_role(
    role_id: uuid.UUID,
    payload: RoleUpdateRequest,
    current_user: User = Depends(get_current_user),
    role_service: RoleService = Depends(get_role_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> RoleOut:
    role = await role_service.get_any_role(role_id)
    await _ensure_can_manage_role(role, current_user, org_service)

    role = await role_service.update_role(
        role_id,
        name=payload.name,
        description=payload.description,
        is_active=payload.is_active,
    )
    return RoleOut.model_validate(role)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    role_service: RoleService = Depends(get_role_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> None:
    role = await role_service.get_any_role(role_id)
    await _ensure_can_manage_role(role, current_user, org_service)
    await role_service.delete_role(role_id)


@router.post(
    "/{role_id}/permissions",
    response_model=RoleWithPermissionsOut,
)
async def add_role_permissions(
    role_id: uuid.UUID,
    payload: AddRolePermissionsRequest,
    current_user: User = Depends(get_current_user),
    role_service: RoleService = Depends(get_role_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> RoleWithPermissionsOut:
    role = await role_service.get_any_role(role_id)
    await _ensure_can_manage_role(role, current_user, org_service)

    updated = await role_service.add_permissions(
        role_id, payload.permission_codes, assigned_by=current_user.id
    )
    return RoleWithPermissionsOut.model_validate(updated)


@router.delete(
    "/{role_id}/permissions/{permission_id}",
    response_model=RoleWithPermissionsOut,
)
async def remove_role_permission(
    role_id: uuid.UUID,
    permission_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    role_service: RoleService = Depends(get_role_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> RoleWithPermissionsOut:
    role = await role_service.get_any_role(role_id)
    await _ensure_can_manage_role(role, current_user, org_service)

    updated = await role_service.remove_permission(role_id, permission_id)
    return RoleWithPermissionsOut.model_validate(updated)


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
