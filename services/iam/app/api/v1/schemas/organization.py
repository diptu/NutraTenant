"""Request/response models for organization lifecycle and membership management."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class OrganizationCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    description: str | None = Field(default=None, max_length=500)


class OrganizationUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    default_attributes: dict[str, Any] | None = None


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    owner_id: uuid.UUID
    is_active: bool
    default_attributes: dict[str, Any]


class AddMemberRequest(BaseModel):
    user_id: uuid.UUID
    role_code: str = Field(default="member", max_length=100)


class OrganizationMemberOut(BaseModel):
    user_id: uuid.UUID
    role_code: str
    is_active: bool


class UpdateMemberRoleRequest(BaseModel):
    role_code: str = Field(min_length=1, max_length=100)


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role_code: str = Field(default="member", max_length=100)


class InvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    role_code: str
    expires_at: datetime
    # Only populated when settings.debug is True — there's no email/
    # notification service in this stack, so dev/test environments get the
    # token directly instead of via a delivered email.
    invitation_token: str | None = None


class AcceptInvitationRequest(BaseModel):
    token: str
