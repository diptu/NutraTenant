from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SimulationResult:
    decision: str
    matched: bool
    matched_rules: list[str]
    evaluation_id: uuid.UUID
