from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.modules.groups.value_objects import GroupMembershipRole, GroupMembershipType


@dataclass(frozen=True, slots=True)
class CreateGroupMembershipCommand:
    user_id: uuid.UUID
    group_id: uuid.UUID
    organization_id: uuid.UUID
    membership_type: GroupMembershipType
    role: GroupMembershipRole
    expires_at: datetime | None
    attributes: dict
    created_by: uuid.UUID | None
