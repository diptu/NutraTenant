from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CloneRoleCommand:
    role_id: uuid.UUID
    name: str
    code: str
    created_by: uuid.UUID | None
