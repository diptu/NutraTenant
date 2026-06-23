from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AddUserPermissionsCommand:
    user_id: uuid.UUID
    codes: list[str]
    tenant_slug: str | None
    granted_by: uuid.UUID
