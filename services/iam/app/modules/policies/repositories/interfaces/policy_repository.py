"""Repository contract for :class:`~app.modules.policies.models.Policy`,
satisfied structurally by
:class:`~app.modules.policies.repositories.sqlalchemy.policy_repository.PolicyRepository`."""

from __future__ import annotations

import uuid
from typing import Protocol

from app.modules.policies.models import Policy


class PolicyRepository(Protocol):
    async def get_by_id(self, entity_id: uuid.UUID) -> Policy | None: ...

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[Policy]: ...

    def add(self, instance: Policy) -> None: ...

    async def delete(self, instance: Policy) -> None: ...

    async def get_by_name(self, name: str) -> Policy | None: ...

    async def list_matching(
        self, resource_type: str, action: str, *, organization_id: uuid.UUID | None = None
    ) -> list[Policy]: ...

    async def count_for_resource_action(self, resource_type: str, action: str) -> int: ...

    async def search_catalog(
        self,
        *,
        status: str | None = None,
        type: str | None = None,
        organization_id: uuid.UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Policy], int]: ...
