from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.modules.policies.models import Policy


@dataclass(frozen=True, slots=True)
class SimulatePolicyQuery:
    policy: Policy
    subject: dict[str, Any]
    resource: dict[str, Any]
    action: str
    context: dict[str, Any] | None = None
