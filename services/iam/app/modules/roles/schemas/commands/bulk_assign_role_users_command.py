from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BulkAssignRoleUsersCommand:
    role_id: uuid.UUID
    user_ids: list[uuid.UUID]
    actor_id: uuid.UUID
