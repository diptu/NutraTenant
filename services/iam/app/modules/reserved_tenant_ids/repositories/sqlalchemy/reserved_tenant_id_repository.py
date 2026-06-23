"""Reserved tenant_id blocklist repository."""

from __future__ import annotations

from app.infrastructure.database.base_repository import BaseRepository
from app.modules.reserved_tenant_ids.models import ReservedTenantId
from sqlalchemy import select


class ReservedTenantIdRepository(BaseRepository[ReservedTenantId]):
    """Persistence access for :class:`ReservedTenantId`."""

    model = ReservedTenantId

    async def get_by_tenant_id(self, tenant_id: str) -> ReservedTenantId | None:
        stmt = select(ReservedTenantId).where(ReservedTenantId.tenant_id == tenant_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
