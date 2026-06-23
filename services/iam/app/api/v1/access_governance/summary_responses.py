"""Response models for GET /api/v1/access/{user_id} (User and Access APIs
Specification) — a read-only "effective access" summary."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel


class AccessSummaryOut(BaseModel):
    user_id: uuid.UUID
    roles: list[str]
    permissions: list[str]
    effective_attributes: dict[str, Any]
