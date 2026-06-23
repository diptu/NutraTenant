from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class UpdateResourceCommand:
    resource_id: uuid.UUID
    requester_id: uuid.UUID
    is_superuser: bool
    description: str | None = None
    tags: dict[str, Any] | None = None
    is_public: bool | None = None
    is_active: bool | None = None
