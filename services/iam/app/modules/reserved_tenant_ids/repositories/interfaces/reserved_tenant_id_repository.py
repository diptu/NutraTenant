"""Repository contract for :class:`~app.modules.reserved_tenant_ids.models.ReservedTenantId`,
satisfied structurally by
:class:`~app.modules.reserved_tenant_ids.repositories.sqlalchemy.reserved_tenant_id_repository.ReservedTenantIdRepository`."""

from __future__ import annotations

import uuid
from typing import Protocol

from app.modules.reserved_tenant_ids.models import ReservedTenantId


class ReservedTenantIdRepository(Protocol):
    async def get_by_id(self, entity_id: uuid.UUID) -> ReservedTenantId | None: ...

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[ReservedTenantId]: ...

    def add(self, instance: ReservedTenantId) -> None: ...

    async def delete(self, instance: ReservedTenantId) -> None: ...

    async def get_by_tenant_id(self, tenant_id: str) -> ReservedTenantId | None: ...
