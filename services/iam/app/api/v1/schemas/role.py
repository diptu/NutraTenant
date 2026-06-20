"""Request/response models for role management — both the global (platform-wide)
catalog and org-scoped custom roles."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class RoleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    code: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$")
    description: str | None = Field(default=None, max_length=500)
    # None = a global, platform-wide role (superuser-only). Set = a role
    # custom to that organization (its owner-only).
    organization_id: uuid.UUID | None = None


class RoleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    description: str | None
    organization_id: uuid.UUID | None
    is_system: bool
    is_active: bool


class AssignRoleRequest(BaseModel):
    user_id: uuid.UUID


class UserRoleOut(BaseModel):
    user_id: uuid.UUID
    role_id: uuid.UUID
    role_code: str


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    resource: str
    action: str


class RoleWithPermissionsOut(RoleOut):
    permissions: list[PermissionOut]


class AddRolePermissionsRequest(BaseModel):
    permission_codes: list[str] = Field(min_length=1)
