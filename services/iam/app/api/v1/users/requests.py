"""Request bodies for user CRUD, search, and attribute management."""

from __future__ import annotations

from typing import Any

from app.modules.users.models import UserStatus
from pydantic import BaseModel, EmailStr, Field


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


class AddUserPermissionsRequest(BaseModel):
    permissions: list[str] = Field(min_length=1)


class RemoveUserPermissionsRequest(BaseModel):
    permissions: list[str] = Field(min_length=1)


class AssignUserRoleRequest(BaseModel):
    """POST /api/v1/users/{user_id}/roles — assigns one of the global
    (platform-wide) roles seeded by RoleService.seed_defaults (admin/member/guest),
    not an org-scoped membership role (see app.modules.organizations.service
    for that). Same underlying RoleService.assign_role as
    POST /roles/{role_id}/assignments, just addressed by role code instead
    of role_id."""

    role: str = Field(min_length=1, max_length=100)


class AddUserToTenantRequest(BaseModel):
    # The target organization's slug (e.g. "apple_corp"), not its id.
    tenant_id: str = Field(min_length=1, max_length=100)
    role: str = Field(default="member", min_length=1, max_length=100)
