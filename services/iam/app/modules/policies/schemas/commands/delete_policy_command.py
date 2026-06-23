from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeletePolicyCommand:
    policy_id: uuid.UUID
    actor_id: uuid.UUID
