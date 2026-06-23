from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.modules.groups.value_objects import GroupType


@dataclass(frozen=True, slots=True)
class CreateGroupCommand:
    name: str
    description: str | None
    organization_id: uuid.UUID
    type: GroupType
    parent_group_id: uuid.UUID | None
    attributes: dict
    metadata: dict
    created_by: uuid.UUID | None
