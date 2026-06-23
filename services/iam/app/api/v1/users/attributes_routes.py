"""GET/PUT /api/v1/user-attributes/{user_id} (User Domain API Specification)
— a thin facade over UserService's existing merge-semantics attribute bag,
distinct from PATCH /users/{user_id}/attributes only by URL shape."""

from __future__ import annotations

import uuid

from app.api.v1.users.attributes_requests import UpdateUserAttributesRequest
from app.api.v1.users.attributes_responses import (
    GetUserAttributesResponse,
    UpdateUserAttributesResponse,
)
from app.modules.auth.dependencies import require_superuser
from app.modules.users.dependencies import get_user_service
from app.modules.users.models import User
from app.modules.users.service import UserService
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/user-attributes", tags=["user-attributes"])


@router.get("/{user_id}", response_model=GetUserAttributesResponse)
async def get_user_attributes(
    user_id: uuid.UUID,
    _admin: User = Depends(require_superuser),
    user_service: UserService = Depends(get_user_service),
) -> GetUserAttributesResponse:
    user = await user_service.get_by_id(user_id)
    return GetUserAttributesResponse(attributes=user.attributes)


@router.put("/{user_id}", response_model=UpdateUserAttributesResponse)
async def update_user_attributes(
    user_id: uuid.UUID,
    payload: UpdateUserAttributesRequest,
    _admin: User = Depends(require_superuser),
    user_service: UserService = Depends(get_user_service),
) -> UpdateUserAttributesResponse:
    """Admin-only, same gate as PATCH /users/{user_id}/attributes — ABAC
    attributes are governance data, not something a user can grant
    themselves."""
    await user_service.update_attributes(user_id, payload.model_dump())
    return UpdateUserAttributesResponse()
