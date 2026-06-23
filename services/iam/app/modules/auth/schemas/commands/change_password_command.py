from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChangePasswordCommand:
    user_id: uuid.UUID
    current_password: str
    new_password: str
