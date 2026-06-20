"""Resource Classification Schema — registering protectable resources with metadata tags
(e.g. ``Confidentiality=High``, ``OwnerID=X``, ``Region=EU``) for a future ABAC policy
engine to evaluate against. No policy engine exists yet; this is catalog management only.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.dependencies import get_current_user, get_resource_service
from app.api.v1.schemas.resource import (
    ResourceCreateRequest,
    ResourceOut,
    ResourceUpdateRequest,
)
from app.domain.exceptions import ResourceNotFoundError
from app.infrastructure.db.models.user import User
from app.services.resource_service import ResourceService

router = APIRouter(prefix="/resources", tags=["resources"])


@router.post("", response_model=ResourceOut, status_code=status.HTTP_201_CREATED)
async def register_resource(
    payload: ResourceCreateRequest,
    current_user: User = Depends(get_current_user),
    resource_service: ResourceService = Depends(get_resource_service),
) -> ResourceOut:
    resource = await resource_service.register(
        name=payload.name,
        type_=payload.type,
        description=payload.description,
        tags=payload.tags,
        is_public=payload.is_public,
        created_by=current_user.id,
    )
    return ResourceOut.model_validate(resource)


@router.get("", response_model=list[ResourceOut])
async def list_resources(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    resource_service: ResourceService = Depends(get_resource_service),
) -> list[ResourceOut]:
    resources = await resource_service.list_visible_to(
        current_user.id,
        is_superuser=current_user.is_superuser,
        limit=limit,
        offset=offset,
    )
    return [ResourceOut.model_validate(r) for r in resources]


@router.get("/{resource_id}", response_model=ResourceOut)
async def get_resource(
    resource_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    resource_service: ResourceService = Depends(get_resource_service),
) -> ResourceOut:
    resource = await resource_service.get(resource_id)
    visible = (
        resource.is_public
        or resource.created_by == current_user.id
        or current_user.is_superuser
    )
    if not visible:
        # 404, not 403 — don't confirm a private resource's existence to non-owners.
        raise ResourceNotFoundError(f"No resource with id '{resource_id}'")
    return ResourceOut.model_validate(resource)


@router.patch("/{resource_id}", response_model=ResourceOut)
async def update_resource(
    resource_id: uuid.UUID,
    payload: ResourceUpdateRequest,
    current_user: User = Depends(get_current_user),
    resource_service: ResourceService = Depends(get_resource_service),
) -> ResourceOut:
    resource = await resource_service.update(
        resource_id,
        requester_id=current_user.id,
        is_superuser=current_user.is_superuser,
        description=payload.description,
        tags=payload.tags,
        is_public=payload.is_public,
        is_active=payload.is_active,
    )
    return ResourceOut.model_validate(resource)


@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resource(
    resource_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    resource_service: ResourceService = Depends(get_resource_service),
) -> None:
    await resource_service.delete(
        resource_id,
        requester_id=current_user.id,
        is_superuser=current_user.is_superuser,
    )
