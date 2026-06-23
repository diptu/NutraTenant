"""Request bodies for the Groups API (groups-group-memberships-api-spec)."""

from __future__ import annotations

import uuid

from app.modules.groups.value_objects import GroupStatus, GroupType
from pydantic import BaseModel, Field


class GroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    type: GroupType = "CUSTOM"
    parent_group_id: uuid.UUID | None = None
    attributes: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    # Escape hatch, same rationale as RoleCreateRequest.tenant_id: explicitly
    # target a tenant other than the caller's current session. Omit it to use
    # the caller's current tenant.
    tenant_id: str | None = None


class GroupUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    type: GroupType | None = None
    status: GroupStatus | None = None
    parent_group_id: uuid.UUID | None = None
    attributes: dict | None = None
    metadata: dict | None = None
