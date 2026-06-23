from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RemoveGroupMemberCommand:
    group_id: uuid.UUID
    user_id: uuid.UUID
