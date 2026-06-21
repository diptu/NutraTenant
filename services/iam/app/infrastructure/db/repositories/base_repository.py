"""Generic CRUD primitives shared by every repository."""

import uuid
from typing import Generic, TypeVar

from app.infrastructure.db.base import Base
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Thin async repository wrapper — shared by 5 call sites, not premature."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, entity_id: uuid.UUID) -> ModelT | None:
        return await self._session.get(self.model, entity_id)

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[ModelT]:
        stmt = select(self.model).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    def add(self, instance: ModelT) -> None:
        self._session.add(instance)

    async def delete(self, instance: ModelT) -> None:
        await self._session.delete(instance)
