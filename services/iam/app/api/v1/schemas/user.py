"""Request/response models for user CRUD, search, and attribute management."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None
    is_active: bool
    is_verified: bool
    is_superuser: bool
    attributes: dict[str, Any]


class UserUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=150)


class UserAttributesUpdateRequest(BaseModel):
    """Merged into the user's existing attribute bag — never a full replace."""

    attributes: dict[str, Any]
