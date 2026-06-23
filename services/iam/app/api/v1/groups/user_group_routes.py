"""/api/v1/user-groups (User Domain API Specification) — a thin,
simplified facade over app.modules.groups.service.GroupService: plain
name+description groups scoped to the caller's session tenant, and
bulk add/single remove for membership. The richer /api/v1/groups API
(hierarchy, ABAC attributes, explicit tenant override) is unaffected —
both sit on the same Group/GroupMembership tables.
"""

from __future__ import annotations

import uuid

from app.api.v1.dependencies import get_current_tenant_slug, get_current_user
from app.api.v1.groups.user_group_requests import AddUserGroupMembersRequest, UserGroupCreateRequest
from app.api.v1.groups.user_group_responses import (
    AddUserGroupMembersResponse,
    CreateUserGroupResponse,
    ListUserGroupsResponse,
    UserGroupOut,
)
from app.modules.groups.dependencies import get_group_service
from app.modules.groups.service import GroupService
from app.modules.users.models import User
from fastapi import APIRouter, Depends, status

router = APIRouter(prefix="/user-groups", tags=["user-groups"])


@router.get("", response_model=ListUserGroupsResponse)
async def list_user_groups(
    current_user: User = Depends(get_current_user),
    session_tenant_id: str | None = Depends(get_current_tenant_slug),
    group_service: GroupService = Depends(get_group_service),
) -> ListUserGroupsResponse:
    organization_id = await group_service.resolve_required_tenant(
        tenant_id=None, session_tenant_id=session_tenant_id
    )
    await group_service.ensure_can_list_groups(organization_id, current_user)

    groups, _total = await group_service.list_paginated(
        organization_id=organization_id,
        page=1,
        page_size=200,
        type=None,
        status=None,
        parent_group_id=None,
        search=None,
    )
    return ListUserGroupsResponse(
        groups=[UserGroupOut(group_id=g.id, name=g.name, description=g.description) for g in groups]
    )


@router.post("", response_model=CreateUserGroupResponse, status_code=status.HTTP_201_CREATED)
async def create_user_group(
    payload: UserGroupCreateRequest,
    current_user: User = Depends(get_current_user),
    session_tenant_id: str | None = Depends(get_current_tenant_slug),
    group_service: GroupService = Depends(get_group_service),
) -> CreateUserGroupResponse:
    organization_id = await group_service.resolve_required_tenant(
        tenant_id=None, session_tenant_id=session_tenant_id
    )
    await group_service.ensure_can_create_group(organization_id, current_user)

    group = await group_service.create_group(
        name=payload.name,
        description=payload.description,
        organization_id=organization_id,
        type="CUSTOM",
        parent_group_id=None,
        attributes={},
        metadata={},
        created_by=current_user.id,
    )
    return CreateUserGroupResponse(group_id=group.id)


@router.post("/{group_id}/members", response_model=AddUserGroupMembersResponse)
async def add_user_group_members(
    group_id: uuid.UUID,
    payload: AddUserGroupMembersRequest,
    current_user: User = Depends(get_current_user),
    group_service: GroupService = Depends(get_group_service),
) -> AddUserGroupMembersResponse:
    group = await group_service.get_group(group_id)
    await group_service.ensure_can_create_membership(group, current_user)

    added_count = await group_service.bulk_add_members(
        group_id,
        payload.user_ids,
        organization_id=group.organization_id,
        created_by=current_user.id,
    )
    return AddUserGroupMembersResponse(added_count=added_count)


@router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user_group_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    group_service: GroupService = Depends(get_group_service),
) -> None:
    group = await group_service.get_group(group_id)
    await group_service.ensure_can_create_membership(group, current_user)

    await group_service.remove_member_by_user(group_id, user_id)
