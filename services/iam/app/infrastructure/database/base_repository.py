"""Generic CRUD primitives shared by every module's repository."""

from __future__ import annotations

import uuid
from typing import Generic, TypeVar

from app.infrastructure.database.base import Base
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Thin async repository wrapper — every module's repository extends this
    for `get_by_id`/`list_all`/`add`/`delete`, adding only its own query
    methods (`get_by_email`, `get_by_slug`, ...)."""

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
