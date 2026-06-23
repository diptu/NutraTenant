from __future__ import annotations

from app.infrastructure.database.session import get_db as get_async_db
from app.modules.access_governance.service import AccessGovernanceService
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["get_access_governance_service"]


def get_access_governance_service(
    session: AsyncSession = Depends(get_async_db),
) -> AccessGovernanceService:
    return AccessGovernanceService(session)
