"""GET/PUT /api/v1/user-profiles/me (User Domain API Specification) — the
caller's own display/locale preferences, distinct from the fuller
GET /users/me Common User Object."""

from __future__ import annotations

from app.api.v1.users.profile_requests import UpdateUserProfileRequest
from app.api.v1.users.profile_responses import (
    GetUserProfileResponse,
    UpdateUserProfileResponse,
    UserProfileSettingsOut,
)
from app.modules.auth.dependencies import get_current_user
from app.modules.users.dependencies import get_user_service
from app.modules.users.models import User
from app.modules.users.service import UserService
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/user-profiles", tags=["user-profiles"])


def _to_out(user: User) -> UserProfileSettingsOut:
    # The spec's own example renders an unset preference as "" rather than
    # null — matched here rather than exposing the column's natural None.
    return UserProfileSettingsOut(
        avatar_url=user.avatar_url or "",
        timezone=user.timezone or "",
        locale=user.locale or "",
    )


@router.get("/me", response_model=GetUserProfileResponse)
async def get_my_profile_settings(
    current_user: User = Depends(get_current_user),
) -> GetUserProfileResponse:
    return GetUserProfileResponse(profile=_to_out(current_user))


@router.put("/me", response_model=UpdateUserProfileResponse)
async def update_my_profile_settings(
    payload: UpdateUserProfileRequest,
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
) -> UpdateUserProfileResponse:
    await user_service.update_profile_settings(
        current_user.id,
        avatar_url=payload.avatar_url,
        timezone=payload.timezone,
        locale=payload.locale,
    )
    return UpdateUserProfileResponse()
