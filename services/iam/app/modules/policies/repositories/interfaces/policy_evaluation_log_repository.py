from __future__ import annotations

import uuid
from typing import Protocol

from app.modules.policies.models import PolicyEvaluationLog


class PolicyEvaluationLogRepository(Protocol):
    async def get_by_id(self, entity_id: uuid.UUID) -> PolicyEvaluationLog | None: ...

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[PolicyEvaluationLog]: ...

    def add(self, instance: PolicyEvaluationLog) -> None: ...

    async def delete(self, instance: PolicyEvaluationLog) -> None: ...
