from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UpdateProfileSettingsCommand:
    user_id: uuid.UUID
    avatar_url: str | None = None
    timezone: str | None = None
    locale: str | None = None
