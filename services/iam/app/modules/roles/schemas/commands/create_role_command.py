from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CreateRoleCommand:
    name: str
    code: str
    description: str | None
    organization_id: uuid.UUID | None = None
    priority: int = 0
    permission_codes: list[str] | None = None
    created_by: uuid.UUID | None = None
