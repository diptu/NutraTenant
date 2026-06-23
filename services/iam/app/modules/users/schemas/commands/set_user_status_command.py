from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.modules.users.models import UserStatus


@dataclass(frozen=True, slots=True)
class SetUserStatusCommand:
    user_id: uuid.UUID
    status: UserStatus
    actor_id: uuid.UUID | None = None
