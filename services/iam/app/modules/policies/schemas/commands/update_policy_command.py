from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UpdatePolicyCommand:
    policy_id: uuid.UUID
    actor_id: uuid.UUID
    display_name: str | None = None
    description: str | None = None
    type: str | None = None
    status: str | None = None
    effect: str | None = None
    priority: int | None = None
    resource_types: list[str] | None = None
    actions: list[str] | None = None
    subjects: dict | None = None
    conditions: dict | None = None
    update_conditions: bool = False
    metadata: dict | None = None
