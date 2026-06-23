from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InviteMemberCommand:
    organization_id: uuid.UUID
    email: str
    invited_by: uuid.UUID
    role_code: str = "member"
    always_reveal_token: bool = False
