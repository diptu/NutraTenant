from __future__ import annotations

from app.core.cache import PermissionCache, get_permission_cache
from app.core.config import Settings, get_settings
from app.infrastructure.database.session import get_db as get_async_db
from app.modules.organizations.service import OrganizationService
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["get_organization_service"]


def get_organization_service(
    session: AsyncSession = Depends(get_async_db),
    permission_cache: PermissionCache = Depends(get_permission_cache),
    settings: Settings = Depends(get_settings),
) -> OrganizationService:
    return OrganizationService(session, permission_cache, settings)
