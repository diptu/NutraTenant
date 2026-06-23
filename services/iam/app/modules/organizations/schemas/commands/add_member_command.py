from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AddMemberCommand:
    organization_id: uuid.UUID
    user_id: uuid.UUID
    invited_by: uuid.UUID | None
    role_code: str = "member"
