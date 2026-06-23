from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UpdateProfileCommand:
    user_id: uuid.UUID
    full_name: str | None
    username: str | None = None
    phone: str | None = None
    avatar_url: str | None = None
    actor_id: uuid.UUID | None = None
