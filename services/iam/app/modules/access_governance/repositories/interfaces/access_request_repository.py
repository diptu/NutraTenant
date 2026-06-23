from __future__ import annotations

import uuid
from typing import Protocol

from app.modules.access_governance.models import AccessRequest


class AccessRequestRepository(Protocol):
    async def get_by_id(self, entity_id: uuid.UUID) -> AccessRequest | None: ...

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[AccessRequest]: ...

    def add(self, instance: AccessRequest) -> None: ...

    async def delete(self, instance: AccessRequest) -> None: ...
