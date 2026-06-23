from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CreateAccessReviewCommand:
    review_scope: str
    organization_id: uuid.UUID | None
    review_type: str
    created_by: uuid.UUID
