from __future__ import annotations

from app.infrastructure.database.session import get_db as get_async_db
from app.modules.tenants.service import TenantService
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["get_tenant_service"]


def get_tenant_service(session: AsyncSession = Depends(get_async_db)) -> TenantService:
    return TenantService(session)
