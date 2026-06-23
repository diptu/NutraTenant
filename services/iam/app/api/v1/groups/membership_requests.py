"""Request bodies for the Group Memberships API
(groups-group-memberships-api-spec)."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.modules.groups.value_objects import GroupMembershipRole, GroupMembershipStatus, GroupMembershipType
from pydantic import BaseModel, Field


class GroupMembershipCreateRequest(BaseModel):
    user_id: uuid.UUID
    group_id: uuid.UUID
    membership_type: GroupMembershipType = "DIRECT"
    role: GroupMembershipRole = "MEMBER"
    expires_at: datetime | None = None
    attributes: dict = Field(default_factory=dict)
    # Validated against the target group's own tenant — see
    # app.modules.groups.service. Omit it to use the caller's current tenant.
    tenant_id: str | None = None


class GroupMembershipUpdateRequest(BaseModel):
    role: GroupMembershipRole | None = None
    status: GroupMembershipStatus | None = None
    expires_at: datetime | None = None
    attributes: dict | None = None
