from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SetupMfaCommand:
    user_id: uuid.UUID
