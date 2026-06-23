from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeleteResourceCommand:
    resource_id: uuid.UUID
    requester_id: uuid.UUID
    is_superuser: bool
