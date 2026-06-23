"""Request bodies for the resource classification catalog."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
