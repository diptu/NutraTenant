from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CreatePolicyCommand:
    name: str
    display_name: str | None
    description: str | None
    type: str
    status: str
    effect: str
    priority: int
    organization_id: uuid.UUID | None
    resource_types: list[str]
    actions: list[str]
    subjects: dict
    conditions: dict | None
    metadata: dict
    created_by: uuid.UUID
