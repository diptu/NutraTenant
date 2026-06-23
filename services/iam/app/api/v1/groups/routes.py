"""Groups API — tenant-scoped group CRUD with parent hierarchy and an ABAC
attribute bag, distinct from app.api.v1.tenants.routes (the Tenant
entity's organization-linking API — see that module's docstring).

Tenant resolution and the owner-or-superuser / member-or-superuser
authorization decisions live in app.modules.groups.service, not here — this
module only parses the request and shapes the response (``_to_out`` is
presentation/serialization, same convention as roles.py/permissions.py, not
a business decision).
"""

from __future__ import annotations

import uuid
from typing import cast

from app.api.v1.dependencies import get_current_tenant_slug, get_current_user
from app.api.v1.groups.requests import GroupCreateRequest, GroupUpdateRequest
from app.api.v1.groups.responses import (
    CreateGroupResponse,
    DeleteGroupResponse,
    GetGroupResponse,
    GroupOut,
    ListGroupsResponse,
    UpdateGroupResponse,
)
from app.modules.groups.dependencies import get_group_service
from app.modules.groups.models import Group
from app.modules.groups.service import GroupService
from app.modules.groups.value_objects import GroupStatus, GroupType
from app.modules.organizations.dependencies import get_organization_service
from app.modules.organizations.service import OrganizationService
from app.modules.users.models import User
from fastapi import APIRouter, Depends, Query, status

router = APIRouter(prefix="/groups", tags=["groups"])


async def _to_out(group: Group, group_service: GroupService, org_service: OrganizationService) -> GroupOut:
    organization = await org_service.get(group.organization_id)
    member_count = await group_service.count_members(group.id)
    return GroupOut(
        id=group.id,
        name=group.name,
        description=group.description,
        tenant_id=organization.slug,
        type=cast(GroupType, group.type),
        status=cast(GroupStatus, group.status),
        parent_group_id=group.parent_group_id,
        attributes=group.attributes,
        metadata=group.extra_metadata,
        member_count=member_count,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


@router.post("", response_model=CreateGroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: GroupCreateRequest,
    current_user: User = Depends(get_current_user),
    session_tenant_id: str | None = Depends(get_current_tenant_slug),
    group_service: GroupService = Depends(get_group_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> CreateGroupResponse:
    organization_id = await group_service.resolve_required_tenant(
        tenant_id=payload.tenant_id, session_tenant_id=session_tenant_id
    )
    await group_service.ensure_can_create_group(organization_id, current_user)

    group = await group_service.create_group(
        name=payload.name,
        description=payload.description,
        organization_id=organization_id,
        type=payload.type,
        parent_group_id=payload.parent_group_id,
        attributes=payload.attributes,
        metadata=payload.metadata,
        created_by=current_user.id,
    )
    return CreateGroupResponse(group=await _to_out(group, group_service, org_service))


@router.get("", response_model=ListGroupsResponse)
async def list_groups(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    type: str | None = Query(default=None),
    status_: str | None = Query(default=None, alias="status"),
    parent_group_id: uuid.UUID | None = Query(default=None),
    search: str | None = Query(default=None),
    tenant_id: str | None = Query(
        default=None,
        description="Override the caller's session tenant — same rationale as "
        "GroupCreateRequest.tenant_id. Requires at least membership in that tenant.",
    ),
    current_user: User = Depends(get_current_user),
    session_tenant_id: str | None = Depends(get_current_tenant_slug),
    group_service: GroupService = Depends(get_group_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> ListGroupsResponse:
    organization_id = await group_service.resolve_required_tenant(
        tenant_id=tenant_id, session_tenant_id=session_tenant_id
    )
    await group_service.ensure_can_list_groups(organization_id, current_user)

    groups, total = await group_service.list_paginated(
        organization_id=organization_id,
        page=page,
        page_size=page_size,
        type=type,
        status=status_,
        parent_group_id=parent_group_id,
        search=search,
    )
    return ListGroupsResponse(
        total=total,
        page=page,
        page_size=page_size,
        groups=[await _to_out(g, group_service, org_service) for g in groups],
    )


@router.get("/{group_id}", response_model=GetGroupResponse)
async def get_group(
    group_id: uuid.UUID,
    _current_user: User = Depends(get_current_user),
    group_service: GroupService = Depends(get_group_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> GetGroupResponse:
    group = await group_service.get_group(group_id)
    return GetGroupResponse(group=await _to_out(group, group_service, org_service))


@router.patch("/{group_id}", response_model=UpdateGroupResponse)
async def update_group(
    group_id: uuid.UUID,
    payload: GroupUpdateRequest,
    current_user: User = Depends(get_current_user),
    group_service: GroupService = Depends(get_group_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> UpdateGroupResponse:
    group = await group_service.get_group(group_id)
    await group_service.ensure_can_manage_group(group, current_user)

    group = await group_service.update_group(
        group_id,
        name=payload.name,
        description=payload.description,
        type=payload.type,
        status=payload.status,
        parent_group_id=payload.parent_group_id,
        attributes=payload.attributes,
        metadata=payload.metadata,
        updated_by=current_user.id,
    )
    return UpdateGroupResponse(group=await _to_out(group, group_service, org_service))


@router.delete("/{group_id}", response_model=DeleteGroupResponse)
async def delete_group(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    group_service: GroupService = Depends(get_group_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> DeleteGroupResponse:
    group = await group_service.get_group(group_id)
    await group_service.ensure_can_manage_group(group, current_user)

    await group_service.delete_group(group_id)
    return DeleteGroupResponse()
