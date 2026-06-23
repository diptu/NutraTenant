"""Repository contract for :class:`~app.modules.resources.models.Resource`,
satisfied structurally by
:class:`~app.modules.resources.repositories.sqlalchemy.resource_repository.ResourceRepository`."""

from __future__ import annotations

import uuid
from typing import Protocol

from app.modules.resources.models import Resource


class ResourceRepository(Protocol):
    async def get_by_id(self, entity_id: uuid.UUID) -> Resource | None: ...

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[Resource]: ...

    def add(self, instance: Resource) -> None: ...

    async def delete(self, instance: Resource) -> None: ...

    async def get_by_name(self, name: str) -> Resource | None: ...

    async def list_visible_to(
        self,
        user_id: uuid.UUID,
        *,
        is_superuser: bool,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Resource]: ...
