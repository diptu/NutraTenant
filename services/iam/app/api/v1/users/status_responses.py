"""Response models for GET/PATCH /api/v1/user-status/{user_id}
(User Domain API Specification)."""

from __future__ import annotations

import uuid

from app.modules.users.models import UserStatus
from pydantic import BaseModel


class UpdateUserStatusResponse(BaseModel):
    user_id: uuid.UUID
    status: UserStatus


class GetUserStatusResponse(BaseModel):
    status: UserStatus
