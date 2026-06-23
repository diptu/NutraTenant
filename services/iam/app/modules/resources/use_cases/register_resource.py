from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.modules.resources.exceptions import ResourceAlreadyExistsError
from app.modules.resources.models import Resource
from app.modules.resources.repositories.interfaces.resource_repository import (
    ResourceRepository,
)
from app.modules.resources.schemas.commands.register_resource_command import (
    RegisterResourceCommand,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class RegisterResourceUseCase:
    def __init__(self, session: AsyncSession, resources: ResourceRepository) -> None:
        self._session = session
        self._resources = resources

    async def execute(self, command: RegisterResourceCommand) -> Resource:
        if await self._resources.get_by_name(command.name) is not None:
            raise ResourceAlreadyExistsError(f"A resource named '{command.name}' already exists")

        now = datetime.now(UTC)
        resource = Resource(
            id=uuid.uuid4(),
            name=command.name,
            type=command.type_,
            description=command.description,
            tags=command.tags,
            is_public=command.is_public,
            is_active=True,
            created_by=command.created_by,
            created_at=now,
            updated_at=now,
        )
        self._resources.add(resource)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ResourceAlreadyExistsError(
                f"A resource named '{command.name}' already exists"
            ) from exc

        await self._session.commit()
        return resource
