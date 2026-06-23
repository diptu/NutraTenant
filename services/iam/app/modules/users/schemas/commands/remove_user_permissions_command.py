from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RemoveUserPermissionsCommand:
    user_id: uuid.UUID
    codes: list[str]
    tenant_slug: str | None
    actor_id: uuid.UUID | None = None
