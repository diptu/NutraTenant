"""Tenant-scoped invitation creation.

A second contract for the same OrganizationService.invite_member already
exposed at POST /organizations/{organization_id}/invitations — this one
matches a different client's expected shape (`tenant_id`/`invite_token`/
`role` instead of `organization_id`/`invitation_token`/`role_code`), not a
different feature.
"""

from __future__ import annotations

import uuid

from app.api.v1.dependencies import (
    get_auth_service,
    get_current_access_claims,
    get_current_user,
    get_organization_service,
    require_superuser,
)
from app.api.v1.schemas.tenant import (
    CreateInviteRequest,
    CreateInviteResponse,
    CreateTenantRequest,
    CreateTenantResponse,
    TenantBootstrapInfo,
    TenantBootstrapOwnerOut,
    TenantDetailOut,
)
from app.core.cache import PermissionCache, get_permission_cache
from app.core.config import Settings, get_settings
from app.domain.exceptions import ForbiddenError, RoleNotFoundError
from app.infrastructure.db.models.user import User
from app.infrastructure.security.jwt import AccessTokenClaims
from app.services.auth_service import AuthService
from app.services.org_permissions import get_member_permissions
from app.services.organization_service import OrganizationService
from app.services.role_lookup import DEFAULT_ORG_ROLES
from fastapi import APIRouter, Depends, status

router = APIRouter(prefix="/tenants", tags=["tenants"])

# Internal role `code` -> the display string this endpoint's contract uses.
# Purely presentational: the stored Role.code/name are untouched (still
# "owner"/"Owner", ...) so every other endpoint built on them is unaffected.
_ROLE_DISPLAY_NAMES = {
    "owner": "TENANT_ADMIN",
    "admin": "ADMIN",
    "member": "MEMBER",
    "viewer": "VIEWER",
}


async def _ensure_can_invite(
    org_service: OrganizationService,
    organization_id: uuid.UUID,
    current_user: User,
    permission_cache: PermissionCache,
) -> None:
    """Owner and superuser always pass (structural bypass, same as
    OrganizationService._ensure_can_grant_role); anyone else needs the
    `tenant:invite` permission code granted to their role."""
    if current_user.is_superuser:
        return
    membership = await org_service.require_membership(organization_id, current_user.id)
    if membership.role.code == "owner":
        return
    permissions = await get_member_permissions(organization_id, membership, cache=permission_cache)
    if "tenant:invite" not in permissions:
        raise ForbiddenError("This action requires the 'tenant:invite' permission")


@router.post(
    "/{tenant_id}/invites",
    response_model=CreateInviteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_tenant_invite(
    tenant_id: str,
    payload: CreateInviteRequest,
    current_user: User = Depends(get_current_user),
    claims: AccessTokenClaims = Depends(get_current_access_claims),
    org_service: OrganizationService = Depends(get_organization_service),
    settings: Settings = Depends(get_settings),
    permission_cache: PermissionCache = Depends(get_permission_cache),
) -> CreateInviteResponse:
    # Existence first: a nonexistent tenant must 404, not 403 — same
    # precedent as GET /organizations/{organization_id}.
    organization = await org_service.get_by_slug(tenant_id)

    # The caller's *current session* must be scoped to this tenant — being
    # a member of it isn't enough if they're currently logged in under a
    # different tenant context (e.g. they belong to several). Superusers
    # bypass this the same way they bypass every other tenant-membership
    # gate in this service.
    if not current_user.is_superuser and claims.tenant_id != tenant_id:
        raise ForbiddenError(
            "Your current session is not scoped to this tenant — log in (or switch-tenant) into it first"
        )

    await _ensure_can_invite(org_service, organization.id, current_user, permission_cache)

    role = await org_service.resolve_role(organization.id, payload.role)
    if role is None:
        raise RoleNotFoundError(f"No role '{payload.role}' exists in tenant '{tenant_id}'")

    _invitation, raw_token = await org_service.invite_member(
        organization.id,
        email=payload.email,
        role_code=role.code,
        invited_by=current_user.id,
        always_reveal_token=True,
    )
    assert raw_token is not None  # guaranteed by always_reveal_token=True

    return CreateInviteResponse(
        invite_token=raw_token,
        expires_in=settings.organization_invitation_expire_minutes * 60,
        tenant_id=organization.slug,
    )


@router.post(
    "",
    response_model=CreateTenantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_tenant(
    payload: CreateTenantRequest,
    _admin: User = Depends(require_superuser),
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> CreateTenantResponse:
    """Root bootstrapping endpoint — provisions a brand-new tenant, its
    standard role set, and maps (or invites) its owner, all atomically.
    Superuser-only: this targets an arbitrary new tenant_id, the same
    platform-ops reasoning as POST /admin/users."""
    result = await auth_service.create_tenant(
        name=payload.name,
        tenant_id=payload.tenant_id,
        owner_email=payload.owner_email,
        plan=payload.plan,
        settings=payload.settings.model_dump(),
        metadata=payload.metadata,
    )
    organization = result.organization
    owner_role_display = _ROLE_DISPLAY_NAMES.get(result.owner_role.code, result.owner_role.code.upper())

    bootstrap = None
    message = "Tenant created and owner assigned successfully"
    if result.is_new_owner:
        assert result.invite_token is not None
        bootstrap = TenantBootstrapInfo(
            invite_token=result.invite_token,
            invite_expiry=settings.organization_invitation_expire_minutes * 60,
            next_step="Invite sent to tenant owner email",
        )
        message = "Tenant created and owner invited successfully"

    return CreateTenantResponse(
        tenant=TenantDetailOut(
            id=str(organization.id),
            tenant_id=organization.slug,
            name=organization.name,
            status="ACTIVE" if organization.is_active else "INACTIVE",
            plan=organization.plan,
            created_at=organization.created_at,
            settings=organization.settings,
            metadata=organization.extra_metadata,
        ),
        owner=TenantBootstrapOwnerOut(
            user_id=str(result.owner.id),
            email=result.owner.email,
            role=owner_role_display,
            status="PENDING_VERIFICATION" if result.is_new_owner else "ACTIVE",
        ),
        default_roles=[_ROLE_DISPLAY_NAMES.get(code, code.upper()) for code, _ in DEFAULT_ORG_ROLES],
        bootstrap=bootstrap,
        message=message,
    )
