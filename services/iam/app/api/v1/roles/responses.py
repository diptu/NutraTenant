"""Response models for role management — both the global (platform-wide)
catalog and tenant-scoped custom roles (Role_API_Specification_Extended.md).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class RoleOut(BaseModel):
    """The Common Role Object."""

    id: uuid.UUID
    tenant_id: str | None
    name: str
    slug: str
    description: str | None
    is_system: bool
    is_active: bool
    priority: int
    permissions_count: int
    users_count: int
    created_by: str | None
    updated_by: str | None
    created_at: datetime
    updated_at: datetime


class CreateRoleResponse(BaseModel):
    message: str = "Role created successfully"
    role: RoleOut


class UpdateRoleResponse(BaseModel):
    message: str = "Role updated successfully"
    role: RoleOut


class GetRoleResponse(BaseModel):
    role: RoleOut


class ListRolesResponse(BaseModel):
    total: int
    page: int
    page_size: int
    roles: list[RoleOut]


class DeleteRoleResponse(BaseModel):
    success: bool = True
    message: str = "Role deleted successfully"


class AssignRolePermissionsResponse(BaseModel):
    success: bool = True
    role_id: uuid.UUID
    permissions_count: int
    message: str = "Permissions assigned successfully"


class RolePermissionItem(BaseModel):
    id: uuid.UUID
    name: str


class GetRolePermissionsResponse(BaseModel):
    role_id: uuid.UUID
    permissions: list[RolePermissionItem]


class RemoveRolePermissionsResponse(BaseModel):
    success: bool = True
    message: str = "Permissions removed successfully"


class AssignUsersToRoleResponse(BaseModel):
    success: bool = True
    assigned_users: int


class RoleUserItem(BaseModel):
    id: uuid.UUID
    name: str | None
    email: str


class GetRoleUsersResponse(BaseModel):
    role_id: uuid.UUID
    total: int
    users: list[RoleUserItem]


class CloneRoleResponse(BaseModel):
    message: str = "Role cloned successfully"
    role: RoleOut


class ActivateRoleResponse(BaseModel):
    success: bool = True
    status: str = "ACTIVE"


class DeactivateRoleResponse(BaseModel):
    success: bool = True
    status: str = "INACTIVE"


class UserRoleOut(BaseModel):
    user_id: uuid.UUID
    role_id: uuid.UUID
    role_code: str
