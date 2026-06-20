"""Request/response models for the resource classification catalog."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResourceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: str = Field(min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=2000)
    tags: dict[str, Any] | None = None
    is_public: bool = False


class ResourceUpdateRequest(BaseModel):
    description: str | None = None
    tags: dict[str, Any] | None = None
    is_public: bool | None = None
    is_active: bool | None = None


class ResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: str
    description: str | None
    tags: dict[str, Any] | None
    is_public: bool
    is_active: bool
    created_by: uuid.UUID | None
