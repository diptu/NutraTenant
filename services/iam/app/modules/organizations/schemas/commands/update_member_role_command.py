from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UpdateMemberRoleCommand:
    organization_id: uuid.UUID
    user_id: uuid.UUID
    new_role_code: str
    actor_id: uuid.UUID
