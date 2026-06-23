from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.modules.groups.value_objects import GroupMembershipRole, GroupMembershipStatus


@dataclass(frozen=True, slots=True)
class UpdateGroupMembershipCommand:
    membership_id: uuid.UUID
    role: GroupMembershipRole | None
    status: GroupMembershipStatus | None
    expires_at: datetime | None
    attributes: dict | None
    updated_by: uuid.UUID | None
