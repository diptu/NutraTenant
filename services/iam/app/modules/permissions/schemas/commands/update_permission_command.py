from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.modules.permissions.value_objects import PermissionRiskLevel


@dataclass(frozen=True, slots=True)
class UpdatePermissionCommand:
    permission_id: uuid.UUID
    description: str | None
    category: str | None
    risk_level: PermissionRiskLevel | None
    updated_by: uuid.UUID | None
