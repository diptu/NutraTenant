from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PublishPolicyCommand:
    policy_id: uuid.UUID
    actor_id: uuid.UUID
    comment: str | None
