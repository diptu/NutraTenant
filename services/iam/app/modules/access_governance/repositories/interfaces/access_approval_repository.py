from __future__ import annotations

import uuid
from typing import Protocol

from app.modules.access_governance.models import AccessApproval


class AccessApprovalRepository(Protocol):
    async def get_by_id(self, entity_id: uuid.UUID) -> AccessApproval | None: ...

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[AccessApproval]: ...

    def add(self, instance: AccessApproval) -> None: ...

    async def delete(self, instance: AccessApproval) -> None: ...
