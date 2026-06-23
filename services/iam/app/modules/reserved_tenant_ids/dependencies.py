from __future__ import annotations

from app.infrastructure.database.session import get_db as get_async_db
from app.modules.reserved_tenant_ids.service import ReservedTenantIdService
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["get_reserved_tenant_id_service"]


def get_reserved_tenant_id_service(
    session: AsyncSession = Depends(get_async_db),
) -> ReservedTenantIdService:
    return ReservedTenantIdService(session)
