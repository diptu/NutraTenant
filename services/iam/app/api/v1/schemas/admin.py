"""Request/response models for platform-admin user provisioning."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field


class AdminCreateUserRequest(BaseModel):
    email: EmailStr
    name: str | None = Field(default=None, max_length=150)
    # The target organization's slug (e.g. "apple_corp"), not its id.
    tenant_id: str
    role: str = Field(min_length=1, max_length=100)


class AdminCreateUserResponse(BaseModel):
    user_id: uuid.UUID
    status: str
    temp_password_sent: bool
