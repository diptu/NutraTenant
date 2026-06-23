from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeletePermissionCommand:
    permission_id: uuid.UUID
