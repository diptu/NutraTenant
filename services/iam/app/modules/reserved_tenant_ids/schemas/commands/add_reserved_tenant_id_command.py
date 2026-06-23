from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AddReservedTenantIdCommand:
    tenant_id: str
    reason: str | None
    created_by: uuid.UUID | None
