from __future__ import annotations

import uuid
from typing import Protocol

from app.modules.access_governance.models import AccessReview


class AccessReviewRepository(Protocol):
    async def get_by_id(self, entity_id: uuid.UUID) -> AccessReview | None: ...

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[AccessReview]: ...

    def add(self, instance: AccessReview) -> None: ...

    async def delete(self, instance: AccessReview) -> None: ...
