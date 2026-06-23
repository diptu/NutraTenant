"""Platform-admin user provisioning — directly into a tenant, no invite
round trip. Superuser-only: unlike tenant invites (scoped by URL to a
tenant the caller already administers), this targets an arbitrary
tenant_id from the request body, so it's gated as a platform-ops action.

DEPRECATED: superseded by POST /api/v1/users, which drives the same
AuthService.provision_user flow but returns the Common User Object
(UserProfileOut — id/name/email/username/tenant/role/permissions/...)
instead of this endpoint's narrower {user_id, status, temp_password_sent}
contract. Kept as-is, unremoved, for existing callers — new integrations
should use POST /api/v1/users.
"""

from __future__ import annotations

from app.api.v1.dependencies import get_auth_service, require_superuser
from app.api.v1.schemas.admin import AdminCreateUserRequest, AdminCreateUserResponse
from app.modules.auth.service import AuthService
from app.modules.users.models import User
from fastapi import APIRouter, Depends, status

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post(
    "/users",
    response_model=AdminCreateUserResponse,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
)
async def admin_create_user(
    payload: AdminCreateUserRequest,
    _admin: User = Depends(require_superuser),
    auth_service: AuthService = Depends(get_auth_service),
) -> AdminCreateUserResponse:
    """Deprecated — use POST /api/v1/users instead (same provisioning flow,
    returns the Common User Object). Kept for backward compatibility."""
    user, _organization, _role, _temp_password = await auth_service.provision_user(
        email=payload.email,
        full_name=payload.name,
        tenant_slug=payload.tenant_id,
        role=payload.role,
    )
    return AdminCreateUserResponse(
        user_id=user.id,
        status="INVITED",
        temp_password_sent=True,
    )
