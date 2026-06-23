from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BulkCreatePermissionsCommand:
    items: list[dict]
    organization_id: uuid.UUID | None
    created_by: uuid.UUID | None
