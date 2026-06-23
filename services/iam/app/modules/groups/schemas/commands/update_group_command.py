from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.modules.groups.value_objects import GroupStatus, GroupType


@dataclass(frozen=True, slots=True)
class UpdateGroupCommand:
    group_id: uuid.UUID
    name: str | None
    description: str | None
    type: GroupType | None
    status: GroupStatus | None
    parent_group_id: uuid.UUID | None
    attributes: dict | None
    metadata: dict | None
    updated_by: uuid.UUID | None
