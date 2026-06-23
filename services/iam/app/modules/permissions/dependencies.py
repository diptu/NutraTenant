from __future__ import annotations

from app.infrastructure.database.session import get_db as get_async_db
from app.modules.permissions.service import PermissionService
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["get_permission_service"]


def get_permission_service(session: AsyncSession = Depends(get_async_db)) -> PermissionService:
    return PermissionService(session)
