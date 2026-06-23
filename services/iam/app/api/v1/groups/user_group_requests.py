"""Request bodies for /api/v1/user-groups (User Domain API
Specification) — a thin, simplified facade over the same Group/
GroupMembership tables the richer /api/v1/groups API manages (hierarchy,
ABAC attributes, tenant overrides — none of which this slimmer contract
exposes)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class UserGroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class AddUserGroupMembersRequest(BaseModel):
    user_ids: list[uuid.UUID] = Field(min_length=1)
