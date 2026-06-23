from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RegisterResourceCommand:
    name: str
    type_: str
    description: str | None
    tags: dict[str, Any] | None
    is_public: bool
    created_by: uuid.UUID
