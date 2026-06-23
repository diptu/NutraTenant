"""Response models for /api/v1/user-groups (User Domain API Specification)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class UserGroupOut(BaseModel):
    group_id: uuid.UUID
    name: str
    description: str | None


class ListUserGroupsResponse(BaseModel):
    groups: list[UserGroupOut]


class CreateUserGroupResponse(BaseModel):
    group_id: uuid.UUID


class AddUserGroupMembersResponse(BaseModel):
    added_count: int
