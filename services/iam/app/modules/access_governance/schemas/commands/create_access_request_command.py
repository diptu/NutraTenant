from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CreateAccessRequestCommand:
    user_id: uuid.UUID
    requested_roles: list[str]
    requested_permissions: list[str]
    justification: str | None
    requested_by: uuid.UUID
