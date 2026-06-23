from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AcceptInvitationCommand:
    raw_token: str
    accepting_user_id: uuid.UUID
    accepting_email: str
