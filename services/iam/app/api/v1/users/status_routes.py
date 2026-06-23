"""GET/PATCH /api/v1/user-status/{user_id} (User Domain API Specification)
— a thin facade over UserService.set_status, distinct from
PATCH /users/{user_id}/status only by URL shape and response field set."""

from __future__ import annotations

import uuid

from app.api.v1.users.status_requests import UpdateUserStatusRequest
from app.api.v1.users.status_responses import (
    GetUserStatusResponse,
    UpdateUserStatusResponse,
)
from app.modules.auth.dependencies import get_current_user, require_superuser
from app.modules.users.dependencies import get_user_service
from app.modules.users.models import User
from app.modules.users.service import UserService, account_status
from app.shared.exceptions.base import ForbiddenError
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/user-status", tags=["user-status"])


@router.get("/{user_id}", response_model=GetUserStatusResponse)
async def get_user_status(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
) -> GetUserStatusResponse:
    if not current_user.is_superuser and current_user.id != user_id:
        raise ForbiddenError("You can only view your own status")
    user = await user_service.get_by_id(user_id)
    return GetUserStatusResponse(status=account_status(user))


@router.patch("/{user_id}", response_model=UpdateUserStatusResponse)
async def update_user_status(
    user_id: uuid.UUID,
    payload: UpdateUserStatusRequest,
    admin: User = Depends(require_superuser),
    user_service: UserService = Depends(get_user_service),
) -> UpdateUserStatusResponse:
    user = await user_service.set_status(user_id, payload.status, actor_id=admin.id)
    return UpdateUserStatusResponse(user_id=user.id, status=account_status(user))
