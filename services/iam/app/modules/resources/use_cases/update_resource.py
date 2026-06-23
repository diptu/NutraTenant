from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.modules.resources.exceptions import ResourceNotFoundError
from app.modules.resources.models import Resource
from app.modules.resources.repositories.interfaces.resource_repository import (
    ResourceRepository,
)
from app.modules.resources.schemas.commands.update_resource_command import (
    UpdateResourceCommand,
)
from app.modules.resources.use_cases._guards import require_owner_or_superuser
from sqlalchemy.ext.asyncio import AsyncSession


class UpdateResourceUseCase:
    def __init__(self, session: AsyncSession, resources: ResourceRepository) -> None:
        self._session = session
        self._resources = resources

    async def execute(self, command: UpdateResourceCommand) -> Resource:
        resource = await self._get(command.resource_id)
        require_owner_or_superuser(resource, command.requester_id, command.is_superuser)

        if command.description is not None:
            resource.description = command.description
        if command.tags is not None:
            resource.tags = command.tags
        if command.is_public is not None:
            resource.is_public = command.is_public
        if command.is_active is not None:
            resource.is_active = command.is_active
        resource.updated_at = datetime.now(UTC)

        await self._session.commit()
        return resource

    async def _get(self, resource_id: uuid.UUID) -> Resource:
        resource = await self._resources.get_by_id(resource_id)
        if resource is None:
            raise ResourceNotFoundError(f"No resource with id '{resource_id}'")
        return resource
