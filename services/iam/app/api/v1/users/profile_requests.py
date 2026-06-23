"""Request bodies for GET/PUT /api/v1/user-profiles/me
(User Domain API Specification)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class UpdateUserProfileRequest(BaseModel):
    avatar_url: str | None = Field(default=None, max_length=500)
    timezone: str | None = Field(default=None, max_length=64)
    locale: str | None = Field(default=None, max_length=20)
