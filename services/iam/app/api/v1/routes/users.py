"""User CRUD, search/filtering, activation, and ABAC attribute management."""

from __future__ import annotations

import uuid

from app.api.v1.dependencies import (
    get_auth_service,
    get_current_access_claims,
    get_current_user,
    get_organization_service,
    get_user_service,
    require_superuser,
)
from app.api.v1.schemas.user import (
    AddUserPermissionsRequest,
    AddUserPermissionsResponse,
    RemoveUserFromTenantResponse,
    RemoveUserPermissionsRequest,
    RemoveUserPermissionsResponse,
    RevokeSessionResponse,
    RoleOut,
    SessionSummaryOut,
    TenantOut,
    UpdateUserStatusRequest,
    UpdateUserStatusResponse,
    UserAttributesUpdateRequest,
    UserCreateRequest,
    UserOut,
    UserProfileOut,
    UserSessionsOut,
    UserUpdateRequest,
)
from app.domain.exceptions import ForbiddenError, OrganizationNotFoundError, SessionNotFoundError
from app.infrastructure.db.models.organization import Organization
from app.infrastructure.db.models.user import User
from app.infrastructure.security.device import describe_device
from app.infrastructure.security.jwt import AccessTokenClaims
from app.services.auth_service import AuthService
from app.services.organization_service import OrganizationService
from app.services.user_service import ProfileContext, UserService, account_status, display_username
from fastapi import APIRouter, Depends, Query, status

router = APIRouter(prefix="/users", tags=["users"])


def _ensure_self_or_superuser(current_user: User, target_user_id: uuid.UUID) -> None:
    if current_user.is_superuser or current_user.id == target_user_id:
        return
    raise ForbiddenError("You can only access your own user record")


async def _resolve_listing_scope(
    current_user: User,
    claims: AccessTokenClaims,
    org_service: OrganizationService,
) -> Organization | None:
    """Who's allowed to list/search users, and how far they can see.

    Superusers get unrestricted (platform-wide) access — `None` means "no
    tenant scope, list everyone". An organization owner/admin instead only
    ever sees the users in the tenant their *current session* is bound to
    (claims.tenant_id) — anyone else (plain member/viewer, or no tenant
    context at all) is forbidden.
    """
    if current_user.is_superuser:
        return None

    if claims.tenant_id is None:
        raise ForbiddenError("This action requires the organization admin role")

    try:
        organization = await org_service.get_by_slug(claims.tenant_id)
    except OrganizationNotFoundError as exc:
        raise ForbiddenError("This action requires the organization admin role") from exc

    membership = await org_service.require_membership(organization.id, current_user.id)
    if membership.role.code not in ("owner", "admin"):
        raise ForbiddenError("This action requires the organization admin role")
    return organization


def _to_profile_out(user: User, context: ProfileContext) -> UserProfileOut:
    """Shared by GET /users/me and GET /users/{user_id} — the only
    difference between the two is how `context` gets resolved."""
    tenant = (
        TenantOut(
            id=str(context.organization.id),
            tenant_id=context.organization.slug,
            name=context.organization.name,
        )
        if context.organization
        else None
    )
    role = RoleOut(id=str(context.role.id), name=context.role.name) if context.role else None
    return UserProfileOut(
        id=user.id,
        name=user.full_name,
        email=user.email,
        username=display_username(user),
        phone=user.phone,
        avatar_url=user.avatar_url,
        status=account_status(user),
        email_verified=user.is_verified,
        mfa_enabled=user.mfa_enabled,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login=user.last_login_at,
        tenant=tenant,
        role=role,
        permissions=context.permissions,
        attributes=user.attributes,
    )


@router.get("/me", response_model=UserProfileOut)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
    claims: AccessTokenClaims = Depends(get_current_access_claims),
    user_service: UserService = Depends(get_user_service),
) -> UserProfileOut:
    context = await user_service.get_profile_context(current_user.id, claims.tenant_id)
    return _to_profile_out(current_user, context)


@router.post("", response_model=UserProfileOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreateRequest,
    _admin: User = Depends(require_superuser),
    auth_service: AuthService = Depends(get_auth_service),
    user_service: UserService = Depends(get_user_service),
) -> UserProfileOut:
    """Superuser-only — provisions a user directly into a tenant (arbitrary
    tenant_id from the request body, no invite round trip). Returns the
    Common User Object. The recommended replacement for the now-deprecated
    POST /admin/users, which drives the same underlying provisioning flow
    but returns that endpoint's narrower {user_id, status,
    temp_password_sent} contract."""
    user, _organization, _role, _temp_password = await auth_service.provision_user(
        email=payload.email,
        full_name=payload.name,
        username=payload.username,
        phone=payload.phone,
        tenant_slug=payload.tenant_id,
        role=payload.role,
        attributes=payload.attributes,
    )
    context = await user_service.get_profile_context(user.id, payload.tenant_id)
    return _to_profile_out(user, context)


@router.get("", response_model=list[UserOut])
async def list_users(
    q: str | None = Query(default=None, description="Search by email or full name"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    claims: AccessTokenClaims = Depends(get_current_access_claims),
    user_service: UserService = Depends(get_user_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> list[UserOut]:
    """Superusers see every user platform-wide; an organization owner/admin
    instead sees only the users belonging to their own tenant (see
    _resolve_listing_scope) — anyone else is forbidden."""
    organization = await _resolve_listing_scope(current_user, claims, org_service)
    if organization is None:
        users = await user_service.search(q, limit=limit, offset=offset)
    else:
        users = await user_service.list_for_organization(organization.id, q, limit=limit, offset=offset)
    return [UserOut.model_validate(u) for u in users]


@router.get("/search", response_model=list[UserProfileOut])
async def search_users(
    q: str | None = Query(default=None, description="Search by email or full name"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    claims: AccessTokenClaims = Depends(get_current_access_claims),
    user_service: UserService = Depends(get_user_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> list[UserProfileOut]:
    """Same search/access scope as GET /users (q/limit/offset, superuser
    sees everyone, an org owner/admin only their own tenant), but returns
    the Common User Object for each match instead of the bare UserOut —
    registered ahead of GET /{user_id} so "search" is never swallowed as a
    user_id path parameter."""
    organization = await _resolve_listing_scope(current_user, claims, org_service)
    if organization is None:
        users = await user_service.search(q, limit=limit, offset=offset)
    else:
        users = await user_service.list_for_organization(organization.id, q, limit=limit, offset=offset)
    # `None` (auto-detect each result's own sole organization) for the
    # unrestricted superuser listing — organization.slug only when results
    # are already scoped to that one tenant, so every result is known to
    # actually be a member of it.
    tenant_slug = organization.slug if organization is not None else None
    results = []
    for user in users:
        context = await user_service.get_profile_context_for_user(user.id, tenant_slug)
        results.append(_to_profile_out(user, context))
    return results


@router.get("/{user_id}", response_model=UserProfileOut)
async def get_user(
    user_id: uuid.UUID,
    tenant_id: str | None = Query(
        default=None,
        description=(
            "Organization slug to scope tenant/role/permissions to, for a user "
            "who belongs to more than one organization. Defaults to their sole "
            "organization when they have exactly one, otherwise omitted."
        ),
    ),
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
) -> UserProfileOut:
    _ensure_self_or_superuser(current_user, user_id)
    user = await user_service.get_by_id(user_id)
    context = await user_service.get_profile_context_for_user(user.id, tenant_id)
    return _to_profile_out(user, context)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
) -> UserOut:
    _ensure_self_or_superuser(current_user, user_id)
    user = await user_service.update_profile(
        user_id,
        full_name=payload.full_name,
        username=payload.username,
        phone=payload.phone,
        avatar_url=payload.avatar_url,
    )
    return UserOut.model_validate(user)


@router.patch("/{user_id}/attributes", response_model=UserOut)
async def update_user_attributes(
    user_id: uuid.UUID,
    payload: UserAttributesUpdateRequest,
    _admin: User = Depends(require_superuser),
    user_service: UserService = Depends(get_user_service),
) -> UserOut:
    """Admin-only: ABAC attributes (Department, Clearance, Cost Center, ...) are
    governance data, not something a user can grant themselves."""
    user = await user_service.update_attributes(user_id, payload.attributes)
    return UserOut.model_validate(user)


@router.post("/{user_id}/activate", response_model=UserOut)
async def activate_user(
    user_id: uuid.UUID,
    _admin: User = Depends(require_superuser),
    user_service: UserService = Depends(get_user_service),
) -> UserOut:
    user = await user_service.set_active(user_id, is_active=True)
    return UserOut.model_validate(user)


@router.post("/{user_id}/deactivate", response_model=UserOut)
async def deactivate_user(
    user_id: uuid.UUID,
    _admin: User = Depends(require_superuser),
    user_service: UserService = Depends(get_user_service),
) -> UserOut:
    user = await user_service.set_active(user_id, is_active=False)
    return UserOut.model_validate(user)


@router.patch("/{user_id}/status", response_model=UpdateUserStatusResponse)
async def update_user_status(
    user_id: uuid.UUID,
    payload: UpdateUserStatusRequest,
    _admin: User = Depends(require_superuser),
    user_service: UserService = Depends(get_user_service),
) -> UpdateUserStatusResponse:
    """Superuser-only — the general lifecycle-status setter that
    activate/deactivate are now thin wrappers around (see
    UserService.set_status). Every non-ACTIVE status blocks the account's
    API access the same way deactivating already did (is_active=False);
    DELETED is a status label only — it does not hard-delete the row, see
    DELETE /users/{user_id} for that."""
    user = await user_service.set_status(user_id, payload.status)
    return UpdateUserStatusResponse(success=True, status=account_status(user))


_TENANT_ID_QUERY = Query(
    default=None,
    description=(
        "Organization slug to scope this grant to, for a user who belongs to "
        "more than one organization. Defaults to their sole organization when "
        "they have exactly one; required (400) otherwise."
    ),
)


@router.post("/{user_id}/permissions", response_model=AddUserPermissionsResponse)
async def add_user_permissions(
    user_id: uuid.UUID,
    payload: AddUserPermissionsRequest,
    tenant_id: str | None = _TENANT_ID_QUERY,
    current_user: User = Depends(require_superuser),
    user_service: UserService = Depends(get_user_service),
) -> AddUserPermissionsResponse:
    """Superuser-only — grants permissions directly to a user, scoped to one
    organization, independent of their role there. Additive only: not yet
    read by the RBAC fast-path or PolicyEngineService (see
    UserPermissionGrant) — stored and merged into the Common User Object's
    `permissions` list. Idempotent: a permission the user already directly
    holds is a no-op. Returns the user's full direct-grant set for that
    organization, not just the codes just added."""
    permissions = await user_service.add_permissions(
        user_id, payload.permissions, tenant_slug=tenant_id, granted_by=current_user.id
    )
    return AddUserPermissionsResponse(success=True, permissions=permissions)


@router.delete("/{user_id}/permissions", response_model=RemoveUserPermissionsResponse)
async def remove_user_permissions(
    user_id: uuid.UUID,
    payload: RemoveUserPermissionsRequest,
    tenant_id: str | None = _TENANT_ID_QUERY,
    _admin: User = Depends(require_superuser),
    user_service: UserService = Depends(get_user_service),
) -> RemoveUserPermissionsResponse:
    """Superuser-only counterpart to POST .../permissions. Idempotent: a
    permission the user doesn't directly hold is a no-op, not an error (only
    an unknown *code* is)."""
    await user_service.remove_permissions(user_id, payload.permissions, tenant_slug=tenant_id)
    return RemoveUserPermissionsResponse(success=True)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    _admin: User = Depends(require_superuser),
    user_service: UserService = Depends(get_user_service),
) -> None:
    await user_service.delete(user_id)


def _parse_session_id(raw: str) -> uuid.UUID:
    """Session ids are rendered as `sess_<jti>` (see auth.SessionOut) —
    accepts that form or a bare UUID. Anything else 404s rather than 422,
    same as any other unrecognized session id."""
    candidate = raw.removeprefix("sess_")
    try:
        return uuid.UUID(candidate)
    except ValueError as exc:
        raise SessionNotFoundError(f"No active session '{raw}' for this user") from exc


@router.get("/{user_id}/sessions", response_model=UserSessionsOut)
async def list_user_sessions(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserSessionsOut:
    """Self-or-superuser — lets a user see their own active sessions (and a
    superuser audit/support anyone's), same gate as GET /users/{user_id}."""
    _ensure_self_or_superuser(current_user, user_id)
    sessions = await auth_service.list_sessions(user_id)
    return UserSessionsOut(
        sessions=[
            SessionSummaryOut(
                session_id=f"sess_{session.id}",
                device=describe_device(session.user_agent),
                ip_address=session.ip_address,
                issued_at=session.issued_at,
                expires_at=session.expires_at,
            )
            for session in sessions
        ]
    )


@router.delete("/{user_id}/sessions/{session_id}", response_model=RevokeSessionResponse)
async def revoke_user_session(
    user_id: uuid.UUID,
    session_id: str,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> RevokeSessionResponse:
    """Self-or-superuser — e.g. "log out of this device", or a superuser
    killing a specific session during an incident, without revoking every
    other session the user has (see AuthService.revoke_session)."""
    _ensure_self_or_superuser(current_user, user_id)
    await auth_service.revoke_session(user_id, _parse_session_id(session_id))
    return RevokeSessionResponse(success=True, message="Session revoked")


@router.delete("/{user_id}/tenants/{tenant_id}", response_model=RemoveUserFromTenantResponse)
async def remove_user_from_tenant(
    user_id: uuid.UUID,
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_organization_service),
) -> RemoveUserFromTenantResponse:
    """A member may always remove *themself* from a tenant; removing someone
    else requires being that tenant's owner or a superuser — same policy as
    DELETE /organizations/{organization_id}/members/{user_id}, just
    addressed by tenant_id (org slug) under /users instead."""
    organization = await org_service.get_by_slug(tenant_id)
    if user_id != current_user.id and not current_user.is_superuser:
        await org_service.require_owner(organization.id, current_user.id)
    await org_service.remove_member(organization.id, user_id)
    return RemoveUserFromTenantResponse(success=True, message="User removed from tenant")
