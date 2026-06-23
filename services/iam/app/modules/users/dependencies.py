"""Users domain dependency providers."""

from __future__ import annotations

from app.infrastructure.database.session import get_db as get_async_db
from app.modules.users.service import UserService
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["get_user_service"]


def get_user_service(session: AsyncSession = Depends(get_async_db)) -> UserService:
    return UserService(session)
