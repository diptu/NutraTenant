"""Resource catalog registration — the "Resource Classification Schema" checklist item."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.domain.exceptions import (
    ForbiddenError,
    ResourceAlreadyExistsError,
    ResourceNotFoundError,
)
from app.infrastructure.db.models.resource import Resource
from app.infrastructure.db.repositories.resource_repo import ResourceRepository
from sqlalchemy.exc import IntegrityError


class ResourceService:
    def __init__(self, session) -> None:
        self._session = session
        self._resources = ResourceRepository(session)

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
        if await self._resources.get_by_name(name) is not None:
            raise ResourceAlreadyExistsError(f"A resource named '{name}' already exists")

        now = datetime.now(UTC)
        resource = Resource(
            id=uuid.uuid4(),
            name=name,
            type=type_,
            description=description,
            tags=tags,
            is_public=is_public,
            is_active=True,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        self._resources.add(resource)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ResourceAlreadyExistsError(f"A resource named '{name}' already exists") from exc

        await self._session.commit()
        return resource

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
        resource = await self.get(resource_id)
        self._require_owner_or_superuser(resource, requester_id, is_superuser)

        if description is not None:
            resource.description = description
        if tags is not None:
            resource.tags = tags
        if is_public is not None:
            resource.is_public = is_public
        if is_active is not None:
            resource.is_active = is_active
        resource.updated_at = datetime.now(UTC)

        await self._session.commit()
        return resource

    async def delete(self, resource_id: uuid.UUID, *, requester_id: uuid.UUID, is_superuser: bool) -> None:
        resource = await self.get(resource_id)
        self._require_owner_or_superuser(resource, requester_id, is_superuser)
        await self._resources.delete(resource)
        await self._session.commit()

    def _require_owner_or_superuser(
        self, resource: Resource, requester_id: uuid.UUID, is_superuser: bool
    ) -> None:
        if is_superuser or resource.created_by == requester_id:
            return
        raise ForbiddenError("Only the resource's creator or an admin can modify it")
