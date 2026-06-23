"""Resource catalog registration — the "Resource Classification Schema" checklist item."""

from __future__ import annotations

import uuid

from app.modules.resources.exceptions import ResourceNotFoundError
from app.modules.resources.models import Resource
from app.modules.resources.repositories.sqlalchemy.resource_repository import (
    ResourceRepository,
)
from app.modules.resources.schemas.commands.delete_resource_command import (
    DeleteResourceCommand,
)
from app.modules.resources.schemas.commands.register_resource_command import (
    RegisterResourceCommand,
)
from app.modules.resources.schemas.commands.update_resource_command import (
    UpdateResourceCommand,
)
from app.modules.resources.use_cases.delete_resource import DeleteResourceUseCase
from app.modules.resources.use_cases.register_resource import RegisterResourceUseCase
from app.modules.resources.use_cases.update_resource import UpdateResourceUseCase


class ResourceService:
    def __init__(self, session) -> None:
        self._session = session
        self._resources = ResourceRepository(session)
        self._register_use_case = RegisterResourceUseCase(session, self._resources)
        self._update_use_case = UpdateResourceUseCase(session, self._resources)
        self._delete_use_case = DeleteResourceUseCase(session, self._resources)

    async def register(
        self,
        *,
        name: str,
        type_: str,
        description: str | None,
        tags: dict | None,
        is_public: bool,
        created_by: uuid.UUID,
    ) -> Resource:
        command = RegisterResourceCommand(
            name=name,
            type_=type_,
            description=description,
            tags=tags,
            is_public=is_public,
            created_by=created_by,
        )
        return await self._register_use_case.execute(command)

    async def get(self, resource_id: uuid.UUID) -> Resource:
        resource = await self._resources.get_by_id(resource_id)
        if resource is None:
            raise ResourceNotFoundError(f"No resource with id '{resource_id}'")
        return resource

    async def list_visible_to(
        self,
        user_id: uuid.UUID,
        *,
        is_superuser: bool,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Resource]:
        return await self._resources.list_visible_to(
            user_id, is_superuser=is_superuser, limit=limit, offset=offset
        )

    async def update(
        self,
        resource_id: uuid.UUID,
        *,
        requester_id: uuid.UUID,
        is_superuser: bool,
        description: str | None = None,
        tags: dict | None = None,
        is_public: bool | None = None,
        is_active: bool | None = None,
    ) -> Resource:
        command = UpdateResourceCommand(
            resource_id=resource_id,
            requester_id=requester_id,
            is_superuser=is_superuser,
            description=description,
            tags=tags,
            is_public=is_public,
            is_active=is_active,
        )
        return await self._update_use_case.execute(command)

    async def delete(self, resource_id: uuid.UUID, *, requester_id: uuid.UUID, is_superuser: bool) -> None:
        command = DeleteResourceCommand(
            resource_id=resource_id, requester_id=requester_id, is_superuser=is_superuser
        )
        await self._delete_use_case.execute(command)
