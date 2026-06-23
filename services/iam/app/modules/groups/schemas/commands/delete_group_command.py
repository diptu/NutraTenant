from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeleteGroupCommand:
    group_id: uuid.UUID
