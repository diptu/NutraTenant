from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UpdateOrganizationCommand:
    organization_id: uuid.UUID
    name: str | None = None
    description: str | None = None
    default_attributes: dict | None = None
    is_reserved: bool | None = None
