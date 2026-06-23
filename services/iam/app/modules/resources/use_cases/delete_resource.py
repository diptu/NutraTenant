from __future__ import annotations

import uuid

from app.modules.resources.exceptions import ResourceNotFoundError
from app.modules.resources.models import Resource
from app.modules.resources.repositories.interfaces.resource_repository import (
    ResourceRepository,
)
from app.modules.resources.schemas.commands.delete_resource_command import (
    DeleteResourceCommand,
)
from app.modules.resources.use_cases._guards import require_owner_or_superuser
from sqlalchemy.ext.asyncio import AsyncSession


class DeleteResourceUseCase:
    def __init__(self, session: AsyncSession, resources: ResourceRepository) -> None:
        self._session = session
        self._resources = resources

    async def execute(self, command: DeleteResourceCommand) -> None:
        resource = await self._get(command.resource_id)
        require_owner_or_superuser(resource, command.requester_id, command.is_superuser)
        await self._resources.delete(resource)
        await self._session.commit()

    async def _get(self, resource_id: uuid.UUID) -> Resource:
        resource = await self._resources.get_by_id(resource_id)
        if resource is None:
            raise ResourceNotFoundError(f"No resource with id '{resource_id}'")
        return resource
