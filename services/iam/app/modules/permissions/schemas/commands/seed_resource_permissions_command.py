from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SeedResourcePermissionsCommand:
    resources: list[str]
    created_by: uuid.UUID | None
