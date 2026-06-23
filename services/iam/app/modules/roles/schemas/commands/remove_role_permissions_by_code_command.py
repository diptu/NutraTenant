from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RemoveRolePermissionsByCodeCommand:
    role_id: uuid.UUID
    codes: list[str]
