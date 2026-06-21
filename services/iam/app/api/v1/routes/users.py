"""User CRUD, search/filtering, activation, and ABAC attribute management."""

from __future__ import annotations

import uuid

from app.api.v1.dependencies import (
    get_current_user,
    get_user_service,
    require_superuser,
)
from app.api.v1.schemas.user import (
    UserAttributesUpdateRequest,
    UserOut,
    UserUpdateRequest,
)
from app.domain.exceptions import ForbiddenError
from app.infrastructure.db.models.user import User
from app.services.user_service import UserService
from fastapi import APIRouter, Depends, Query, status

router = APIRouter(prefix="/users", tags=["users"])


def _ensure_self_or_superuser(current_user: User, target_user_id: uuid.UUID) -> None:
    if current_user.is_superuser or current_user.id == target_user_id:
        return
    raise ForbiddenError("You can only access your own user record")


@router.get("/me", response_model=UserOut)
async def get_my_profile(current_user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)


@router.get("", response_model=list[UserOut])
async def list_users(
    q: str | None = Query(default=None, description="Search by email or full name"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_superuser),
    user_service: UserService = Depends(get_user_service),
) -> list[UserOut]:
    users = await user_service.search(q, limit=limit, offset=offset)
    return [UserOut.model_validate(u) for u in users]


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
) -> UserOut:
    _ensure_self_or_superuser(current_user, user_id)
    user = await user_service.get_by_id(user_id)
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
) -> UserOut:
    _ensure_self_or_superuser(current_user, user_id)
    user = await user_service.update_profile(user_id, full_name=payload.full_name)
    return UserOut.model_validate(user)


@router.patch("/{user_id}/attributes", response_model=UserOut)
async def update_user_attributes(
    user_id: uuid.UUID,
    payload: UserAttributesUpdateRequest,
    _admin: User = Depends(require_superuser),
    user_service: UserService = Depends(get_user_service),
) -> UserOut:
    """Admin-only: ABAC attributes (Department, Clearance, Cost Center, ...) are
    governance data, not something a user can grant themselves."""
    user = await user_service.update_attributes(user_id, payload.attributes)
    return UserOut.model_validate(user)


@router.post("/{user_id}/activate", response_model=UserOut)
async def activate_user(
    user_id: uuid.UUID,
    _admin: User = Depends(require_superuser),
    user_service: UserService = Depends(get_user_service),
) -> UserOut:
    user = await user_service.set_active(user_id, is_active=True)
    return UserOut.model_validate(user)


@router.post("/{user_id}/deactivate", response_model=UserOut)
async def deactivate_user(
    user_id: uuid.UUID,
    _admin: User = Depends(require_superuser),
    user_service: UserService = Depends(get_user_service),
) -> UserOut:
    user = await user_service.set_active(user_id, is_active=False)
    return UserOut.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    _admin: User = Depends(require_superuser),
    user_service: UserService = Depends(get_user_service),
) -> None:
    await user_service.delete(user_id)
