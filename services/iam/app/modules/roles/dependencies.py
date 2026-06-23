from __future__ import annotations

from app.infrastructure.database.session import get_db as get_async_db
from app.modules.roles.service import RoleService
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["get_role_service"]


def get_role_service(session: AsyncSession = Depends(get_async_db)) -> RoleService:
    return RoleService(session)
