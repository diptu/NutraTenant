"""Tenant repository."""

from app.infrastructure.db.models.tenant import Tenant
from app.infrastructure.db.repositories.base_repository import BaseRepository
from sqlalchemy import select


class TenantRepository(BaseRepository[Tenant]):
    """Persistence access for :class:`Tenant`."""

    model = Tenant

    async def get_by_slug(self, slug: str) -> Tenant | None:
        stmt = select(Tenant).where(Tenant.slug == slug)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
