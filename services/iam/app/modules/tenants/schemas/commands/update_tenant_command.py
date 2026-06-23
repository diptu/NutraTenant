from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UpdateTenantCommand:
    tenant_id: uuid.UUID
    name: str | None = None
    is_active: bool | None = None
