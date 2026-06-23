"""Resource catalog repository."""

from __future__ import annotations

import uuid

from app.infrastructure.database.base_repository import BaseRepository
from app.modules.resources.models import Resource
from sqlalchemy import or_, select


class ResourceRepository(BaseRepository[Resource]):
    """Persistence access for :class:`Resource`."""

    model = Resource

    async def get_by_name(self, name: str) -> Resource | None:
        stmt = select(Resource).where(Resource.name == name)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_visible_to(
        self,
        user_id: uuid.UUID,
        *,
        is_superuser: bool,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Resource]:
        """Public resources, plus the caller's own — superusers see everything."""
        stmt = select(Resource).limit(limit).offset(offset)
        if not is_superuser:
            stmt = stmt.where(or_(Resource.is_public, Resource.created_by == user_id))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
