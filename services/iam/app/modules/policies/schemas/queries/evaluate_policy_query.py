from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.modules.users.models import User


@dataclass(frozen=True, slots=True)
class EvaluatePolicyQuery:
    subject: User
    resource_type: str
    action: str
    resource_id: uuid.UUID | None = None
    resource_attributes: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    organization_id: uuid.UUID | None = None
