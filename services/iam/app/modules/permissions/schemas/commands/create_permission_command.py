from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.modules.permissions.value_objects import PermissionRiskLevel


@dataclass(frozen=True, slots=True)
class CreatePermissionCommand:
    resource: str
    action: str
    description: str | None
    category: str | None
    risk_level: PermissionRiskLevel
    organization_id: uuid.UUID | None
    created_by: uuid.UUID | None
