from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CreateAccessApprovalCommand:
    request_id: uuid.UUID
    decision: str
    comment: str | None
    processed_by: uuid.UUID
