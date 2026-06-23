from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BulkAddGroupMembersCommand:
    group_id: uuid.UUID
    user_ids: list[uuid.UUID]
    organization_id: uuid.UUID
    created_by: uuid.UUID | None
