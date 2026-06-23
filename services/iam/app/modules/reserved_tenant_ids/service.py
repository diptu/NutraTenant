"""Reserved tenant_id blocklist management — backs POST/GET/DELETE
/api/v1/reserved-tenant-ids. Consulted by OrganizationService.create and
AuthService's tenant-provisioning path (both reject a reserved tenant_id
before it ever becomes an Organization.slug).
"""

from __future__ import annotations

import uuid

from app.modules.reserved_tenant_ids.models import ReservedTenantId
from app.modules.reserved_tenant_ids.repositories.sqlalchemy.reserved_tenant_id_repository import (
    ReservedTenantIdRepository,
)
from app.modules.reserved_tenant_ids.schemas.commands.add_reserved_tenant_id_command import (
    AddReservedTenantIdCommand,
)
from app.modules.reserved_tenant_ids.schemas.commands.remove_reserved_tenant_id_command import (
    RemoveReservedTenantIdCommand,
)
from app.modules.reserved_tenant_ids.use_cases.add_reserved_tenant_id import (
    AddReservedTenantIdUseCase,
)
from app.modules.reserved_tenant_ids.use_cases.remove_reserved_tenant_id import (
    RemoveReservedTenantIdUseCase,
)


class ReservedTenantIdService:
    def __init__(self, session) -> None:
        self._session = session
        self._reserved = ReservedTenantIdRepository(session)
        self._add_use_case = AddReservedTenantIdUseCase(session, self._reserved)
        self._remove_use_case = RemoveReservedTenantIdUseCase(session, self._reserved)

    async def list_all(self) -> list[ReservedTenantId]:
        return await self._reserved.list_all(limit=500)

    async def add(
        self, *, tenant_id: str, reason: str | None, created_by: uuid.UUID | None
    ) -> ReservedTenantId:
        command = AddReservedTenantIdCommand(tenant_id=tenant_id, reason=reason, created_by=created_by)
        return await self._add_use_case.execute(command)

    async def remove(self, tenant_id: str) -> None:
        command = RemoveReservedTenantIdCommand(tenant_id=tenant_id)
        await self._remove_use_case.execute(command)
