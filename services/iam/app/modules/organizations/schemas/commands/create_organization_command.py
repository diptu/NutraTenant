from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CreateOrganizationCommand:
    name: str
    slug: str
    description: str | None
    owner_id: uuid.UUID
