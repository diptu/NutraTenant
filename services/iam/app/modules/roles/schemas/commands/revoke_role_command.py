from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RevokeRoleCommand:
    user_id: uuid.UUID
    role_id: uuid.UUID
