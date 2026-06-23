from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.modules.permissions.value_objects import PermissionStatus


@dataclass(frozen=True, slots=True)
class SetPermissionStatusCommand:
    permission_id: uuid.UUID
    status: PermissionStatus
    actor_id: uuid.UUID | None
