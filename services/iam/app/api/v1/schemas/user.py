"""Request/response models for user CRUD, search, and attribute management."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.value_objects import UserStatus
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None
    is_active: bool
    is_verified: bool
    is_superuser: bool
    attributes: dict[str, Any]


class UserCreateRequest(BaseModel):
    """POST /api/v1/users — admin-provisions a user directly into a tenant,
    same underlying flow as POST /admin/users (AuthService.provision_user):
    no password in the request, a temp one is generated server-side and
    `must_change_password` is set."""

    name: str | None = Field(default=None, max_length=150)
    email: EmailStr
    username: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, max_length=32)
    # The target organization's slug (e.g. "apple_corp"), not its id.
    tenant_id: str = Field(min_length=1, max_length=100)
    role: str = Field(min_length=1, max_length=100)
    attributes: dict[str, Any] = Field(default_factory=dict)


class UserUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=150)
    username: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, max_length=32)
    avatar_url: str | None = Field(default=None, max_length=500)


class UserAttributesUpdateRequest(BaseModel):
    """Merged into the user's existing attribute bag — never a full replace."""

    attributes: dict[str, Any]


class UpdateUserStatusRequest(BaseModel):
    status: UserStatus


class UpdateUserStatusResponse(BaseModel):
    success: bool
    status: UserStatus


class AddUserPermissionsRequest(BaseModel):
    permissions: list[str] = Field(min_length=1)


class AddUserPermissionsResponse(BaseModel):
    success: bool
    permissions: list[str]


class RemoveUserPermissionsRequest(BaseModel):
    permissions: list[str] = Field(min_length=1)


class RemoveUserPermissionsResponse(BaseModel):
    success: bool


class SessionSummaryOut(BaseModel):
    """One row of GET /users/{user_id}/sessions — distinct from the fuller
    auth.SessionOut (login response), which also carries `last_login`, an
    account-level field that doesn't belong on a per-session listing."""

    session_id: str
    device: str
    ip_address: str | None
    issued_at: datetime
    expires_at: datetime


class UserSessionsOut(BaseModel):
    sessions: list[SessionSummaryOut]


class RevokeSessionResponse(BaseModel):
    success: bool
    message: str


class RemoveUserFromTenantResponse(BaseModel):
    success: bool
    message: str


class TenantOut(BaseModel):
    """The tenant a session/profile is currently bound to — also used by
    the login response (see app.api.v1.schemas.auth)."""

    id: str
    tenant_id: str
    name: str


class RoleOut(BaseModel):
    """Minimal role descriptor for a tenant-bound session/profile — distinct
    from the full role-CRUD ``RoleOut`` in app.api.v1.schemas.role."""

    id: str
    name: str


class UserProfileOut(BaseModel):
    """Common single-user response — used by both GET /users/me (the
    caller's own profile, tenant context from AccessTokenClaims.tenant_id)
    and GET /users/{user_id} (an arbitrary user, tenant context resolved by
    app.services.user_service.UserService.get_profile_context_for_user)."""

    id: uuid.UUID
    name: str | None
    email: str
    # The real `username` column when set, else derived from the email's
    # local part — see app.services.user_service.display_username.
    username: str
    phone: str | None
    avatar_url: str | None
    status: UserStatus
    email_verified: bool
    mfa_enabled: bool
    created_at: datetime
    updated_at: datetime
    last_login: datetime | None
    tenant: TenantOut | None
    role: RoleOut | None
    permissions: list[str]
    attributes: dict[str, Any]
