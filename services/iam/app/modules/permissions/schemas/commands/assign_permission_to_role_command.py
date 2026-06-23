from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AssignPermissionToRoleCommand:
    permission_id: uuid.UUID
    role_id: uuid.UUID
    assigned_by: uuid.UUID | None
