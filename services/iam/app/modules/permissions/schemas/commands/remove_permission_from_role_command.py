from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RemovePermissionFromRoleCommand:
    permission_id: uuid.UUID
    role_id: uuid.UUID
