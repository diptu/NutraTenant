from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RemoveRolePermissionCommand:
    role_id: uuid.UUID
    permission_id: uuid.UUID
