from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AddRolePermissionsCommand:
    role_id: uuid.UUID
    codes: list[str]
    assigned_by: uuid.UUID
