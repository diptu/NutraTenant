"""Response models for the Groups API (groups-group-memberships-api-spec)."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.modules.groups.value_objects import GroupStatus, GroupType
from pydantic import BaseModel, ConfigDict


class GroupOut(BaseModel):
    """The Common Group Object."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    tenant_id: str
    type: GroupType
    status: GroupStatus
    parent_group_id: uuid.UUID | None
    attributes: dict
    metadata: dict
    member_count: int
    created_at: datetime
    updated_at: datetime


class CreateGroupResponse(BaseModel):
    group: GroupOut


class GetGroupResponse(BaseModel):
    group: GroupOut


class UpdateGroupResponse(BaseModel):
    group: GroupOut


class ListGroupsResponse(BaseModel):
    total: int
    page: int
    page_size: int
    groups: list[GroupOut]


class DeleteGroupResponse(BaseModel):
    success: bool = True
    message: str = "Group deleted successfully"
