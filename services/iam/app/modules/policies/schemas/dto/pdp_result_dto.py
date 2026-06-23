from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PolicyMatchResult:
    policy_id: uuid.UUID
    policy_name: str
    effect: str
    matched: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy_id": str(self.policy_id),
            "policy_name": self.policy_name,
            "effect": self.effect,
            "matched": self.matched,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class PDPResult:
    decision: str
    matched_policies: list[PolicyMatchResult] = field(default_factory=list)
    subject_snapshot: dict[str, Any] = field(default_factory=dict)
    resource_snapshot: dict[str, Any] = field(default_factory=dict)
    context_snapshot: dict[str, Any] = field(default_factory=dict)
    log_id: uuid.UUID | None = None

    @property
    def is_allowed(self) -> bool:
        return self.decision == "allow"
