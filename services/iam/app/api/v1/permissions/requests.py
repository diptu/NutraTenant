"""Request bodies for the Permission Management API."""

from __future__ import annotations

import uuid

from app.modules.permissions.value_objects import PermissionRiskLevel
from pydantic import BaseModel, Field


class PermissionCreateRequest(BaseModel):
    resource: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$")
    action: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$")
    description: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, max_length=100)
    risk_level: PermissionRiskLevel = "LOW"


class PermissionUpdateRequest(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, max_length=100)
    risk_level: PermissionRiskLevel | None = None


class BulkCreatePermissionItem(BaseModel):
    resource: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$")
    action: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$")
    description: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, max_length=100)
    risk_level: PermissionRiskLevel = "LOW"


class BulkCreatePermissionsRequest(BaseModel):
    permissions: list[BulkCreatePermissionItem] = Field(min_length=1)


class SeedPermissionsRequest(BaseModel):
    resources: list[str] = Field(min_length=1)


class AssignPermissionToRoleRequest(BaseModel):
    role_id: uuid.UUID
