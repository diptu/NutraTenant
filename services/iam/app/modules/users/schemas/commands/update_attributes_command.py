from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UpdateAttributesCommand:
    user_id: uuid.UUID
    patch: dict
