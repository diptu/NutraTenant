from __future__ import annotations

from app.infrastructure.database.session import get_db as get_async_db
from app.modules.policies.service import PolicyEngineService, PolicyService
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["get_policy_engine_service", "get_policy_service"]


def get_policy_service(session: AsyncSession = Depends(get_async_db)) -> PolicyService:
    return PolicyService(session)


def get_policy_engine_service(
    session: AsyncSession = Depends(get_async_db),
) -> PolicyEngineService:
    return PolicyEngineService(session)
