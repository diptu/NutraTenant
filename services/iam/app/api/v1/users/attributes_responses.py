"""Response models for GET/PUT /api/v1/user-attributes/{user_id}
(User Domain API Specification)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GetUserAttributesResponse(BaseModel):
    attributes: dict[str, Any]


class UpdateUserAttributesResponse(BaseModel):
    success: bool = Field(default=True)
