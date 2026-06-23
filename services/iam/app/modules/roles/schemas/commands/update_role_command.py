from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UpdateRoleCommand:
    role_id: uuid.UUID
    name: str | None = None
    description: str | None = None
    priority: int | None = None
    is_active: bool | None = None
    updated_by: uuid.UUID | None = None
