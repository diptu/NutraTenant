from __future__ import annotations

from app.infrastructure.database.session import get_db as get_async_db
from app.modules.resources.service import ResourceService
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["get_resource_service"]


def get_resource_service(
    session: AsyncSession = Depends(get_async_db),
) -> ResourceService:
    return ResourceService(session)
