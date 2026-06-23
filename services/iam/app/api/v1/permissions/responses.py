"""Response models for the Permission Management API."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.modules.permissions.value_objects import PermissionRiskLevel, PermissionStatus
from pydantic import BaseModel, ConfigDict


class PermissionOut(BaseModel):
    """The Common Permission Object."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    resource: str
    action: str
    description: str | None
    category: str | None
    risk_level: PermissionRiskLevel
    # The owning organization's slug — None for a global/platform permission.
    tenant_id: str | None
    is_system: bool
    status: PermissionStatus
    created_at: datetime
    updated_at: datetime


class CreatePermissionResponse(BaseModel):
    permission: PermissionOut
    message: str = "Permission created successfully"


class UpdatePermissionResponse(BaseModel):
    permission: PermissionOut
    message: str = "Permission updated successfully"


class GetPermissionResponse(BaseModel):
    permission: PermissionOut


class ListPermissionsResponse(BaseModel):
    total: int
    page: int
    page_size: int
    permissions: list[PermissionOut]


class DeletePermissionResponse(BaseModel):
    success: bool = True
    message: str = "Permission deleted successfully"


class BulkCreatePermissionsResponse(BaseModel):
    created: int
    failed: int


class SeedPermissionsResponse(BaseModel):
    created_permissions: list[str]


class SearchPermissionsResponse(BaseModel):
    results: list[PermissionOut]


class AssignPermissionToRoleResponse(BaseModel):
    success: bool = True
    message: str = "Permission assigned successfully"


class RemovePermissionFromRoleResponse(BaseModel):
    success: bool = True


class PermissionRoleItem(BaseModel):
    id: uuid.UUID
    name: str


class GetPermissionRolesResponse(BaseModel):
    roles: list[PermissionRoleItem]


class GetPermissionUsageResponse(BaseModel):
    users_count: int
    roles_count: int
    policies_count: int


class EnablePermissionResponse(BaseModel):
    status: PermissionStatus = "ACTIVE"


class DisablePermissionResponse(BaseModel):
    status: PermissionStatus = "DISABLED"


class AuditEventItem(BaseModel):
    event: str
    timestamp: datetime


class GetPermissionAuditResponse(BaseModel):
    events: list[AuditEventItem]
