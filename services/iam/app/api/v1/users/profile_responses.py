"""Response models for GET/PUT /api/v1/user-profiles/me
(User Domain API Specification)."""

from __future__ import annotations

from pydantic import BaseModel


class UserProfileSettingsOut(BaseModel):
    avatar_url: str
    timezone: str
    locale: str


class GetUserProfileResponse(BaseModel):
    profile: UserProfileSettingsOut


class UpdateUserProfileResponse(BaseModel):
    success: bool = True
