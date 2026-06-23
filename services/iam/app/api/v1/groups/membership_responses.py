"""Response models for the Group Memberships API
(groups-group-memberships-api-spec)."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.modules.groups.value_objects import GroupMembershipRole, GroupMembershipStatus, GroupMembershipType
from pydantic import BaseModel, ConfigDict


class GroupMembershipOut(BaseModel):
    """The Common Group Membership Object."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    group_id: uuid.UUID
    tenant_id: str
    membership_type: GroupMembershipType
    role: GroupMembershipRole
    status: GroupMembershipStatus
    expires_at: datetime | None
    attributes: dict
    created_at: datetime
    updated_at: datetime


class CreateGroupMembershipResponse(BaseModel):
    membership: GroupMembershipOut


class GetGroupMembershipResponse(BaseModel):
    membership: GroupMembershipOut


class UpdateGroupMembershipResponse(BaseModel):
    membership: GroupMembershipOut


class ListGroupMembershipsResponse(BaseModel):
    total: int
    page: int
    page_size: int
    memberships: list[GroupMembershipOut]


class DeleteGroupMembershipResponse(BaseModel):
    success: bool = True
    message: str = "Group membership deleted successfully"
