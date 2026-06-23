from __future__ import annotations

from app.infrastructure.database.session import get_db as get_async_db
from app.modules.groups.service import GroupService
from app.modules.organizations.dependencies import get_organization_service
from app.modules.organizations.service import OrganizationService
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["get_group_service"]


def get_group_service(
    session: AsyncSession = Depends(get_async_db),
    org_service: OrganizationService = Depends(get_organization_service),
) -> GroupService:
    return GroupService(session, org_service=org_service)
