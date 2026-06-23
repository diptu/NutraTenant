"""Response models for user CRUD, search, and attribute management."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.modules.users.models import UserStatus
from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None
    is_active: bool
    is_verified: bool
    is_superuser: bool
    attributes: dict[str, Any]


class UpdateUserStatusResponse(BaseModel):
    success: bool
    status: UserStatus


class AddUserPermissionsResponse(BaseModel):
    success: bool
    permissions: list[str]


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


class AssignUserRoleResponse(BaseModel):
    user_id: str
    role: str
    message: str


class RemoveUserRoleResponse(BaseModel):
    success: bool
    message: str


class AddUserToTenantResponse(BaseModel):
    success: bool
    tenant_id: str


class TenantOut(BaseModel):
    """The tenant a session/profile is currently bound to — also used by
    the login response (see app.api.v1.auth.responses)."""

    id: str
    tenant_id: str
    name: str


class RoleOut(BaseModel):
    """Minimal role descriptor for a tenant-bound session/profile — distinct
    from the full role-CRUD ``RoleOut`` in app.api.v1.roles.responses."""

    id: str
    name: str


class UserProfileOut(BaseModel):
    """Common single-user response — used by both GET /users/me (the
    caller's own profile, tenant context resolved dynamically via
    app.modules.auth.dependencies.get_current_tenant_slug) and
    GET /users/{user_id} (an arbitrary user, tenant context resolved by
    app.modules.users.service.UserService.get_profile_context_for_user)."""

    id: uuid.UUID
    name: str | None
    email: str
    # The real `username` column when set, else derived from the email's
    # local part — see app.modules.users.service.display_username.
    username: str
    phone: str | None
    avatar_url: str | None
    status: UserStatus
    email_verified: bool
    mfa_enabled: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime
    last_login: datetime | None
    tenant: TenantOut | None
    role: RoleOut | None
    permissions: list[str]
    attributes: dict[str, Any]
