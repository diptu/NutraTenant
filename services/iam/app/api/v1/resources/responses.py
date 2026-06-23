"""Response models for the resource classification catalog."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict


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
