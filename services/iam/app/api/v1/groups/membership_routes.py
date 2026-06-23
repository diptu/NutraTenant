"""Group Memberships API — adding/removing users from a Group, with an
optional ``expires_at`` and per-membership ABAC attribute bag.

A membership's tenant is always its group's tenant (no separate tenant
column — see app.modules.groups.models). Tenant resolution and every
owner-or-superuser / member-or-superuser / self-or-superuser authorization
decision live in app.modules.groups.service, not here — this module only
parses the request and shapes the response.
"""

from __future__ import annotations

import uuid
from typing import cast

from app.api.v1.dependencies import get_current_tenant_slug, get_current_user
from app.api.v1.groups.membership_requests import (
    GroupMembershipCreateRequest,
    GroupMembershipUpdateRequest,
)
from app.api.v1.groups.membership_responses import (
    CreateGroupMembershipResponse,
    DeleteGroupMembershipResponse,
    GetGroupMembershipResponse,
    GroupMembershipOut,
    ListGroupMembershipsResponse,
    UpdateGroupMembershipResponse,
)
from app.modules.groups.dependencies import get_group_service
from app.modules.groups.models import GroupMembership
from app.modules.groups.service import GroupService
from app.modules.groups.value_objects import GroupMembershipRole, GroupMembershipStatus, GroupMembershipType
from app.modules.organizations.dependencies import get_organization_service
from app.modules.organizations.service import OrganizationService
from app.modules.users.models import User
from fastapi import APIRouter, Depends, Query, status

router = APIRouter(prefix="/group-memberships", tags=["group-memberships"])


async def _to_out(
    membership: GroupMembership, group_service: GroupService, org_service: OrganizationService
) -> GroupMembershipOut:
    """Resolves the owning tenant via a fresh ``Group`` lookup rather than
    ``membership.group`` — that relationship is ``lazy="raise"`` and usually
    isn't eager-loaded along the read paths that reach here."""
    group = await group_service.get_group(membership.group_id)
    organization = await org_service.get(group.organization_id)
    return GroupMembershipOut(
        id=membership.id,
        user_id=membership.user_id,
        group_id=membership.group_id,
        tenant_id=organization.slug,
        membership_type=cast(GroupMembershipType, membership.membership_type),
        role=cast(GroupMembershipRole, membership.role),
        status=cast(GroupMembershipStatus, membership.status),
        expires_at=membership.expires_at,
        attributes=membership.attributes,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
    )


@router.post("", response_model=CreateGroupMembershipResponse, status_code=status.HTTP_201_CREATED)
async def create_group_membership(
    payload: GroupMembershipCreateRequest,
    current_user: User = Depends(get_current_user),
    session_tenant_id: str | None = Depends(get_current_tenant_slug),
    group_service: GroupService = Depends(get_group_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> CreateGroupMembershipResponse:
    group = await group_service.get_group(payload.group_id)
    await group_service.ensure_can_create_membership(group, current_user)

    organization_id = await group_service.resolve_optional_tenant(
        tenant_id=payload.tenant_id, session_tenant_id=session_tenant_id
    )
    membership = await group_service.create_membership(
        user_id=payload.user_id,
        group_id=payload.group_id,
        organization_id=organization_id or group.organization_id,
        membership_type=payload.membership_type,
        role=payload.role,
        expires_at=payload.expires_at,
        attributes=payload.attributes,
        created_by=current_user.id,
    )
    return CreateGroupMembershipResponse(membership=await _to_out(membership, group_service, org_service))


@router.get("", response_model=ListGroupMembershipsResponse)
async def list_group_memberships(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    group_id: uuid.UUID | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
    status_: str | None = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
    group_service: GroupService = Depends(get_group_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> ListGroupMembershipsResponse:
    await group_service.ensure_can_list_memberships(
        group_id=group_id, user_id=user_id, current_user=current_user
    )

    memberships, total = await group_service.list_memberships_paginated(
        group_id=group_id,
        user_id=user_id,
        status=status_,
        page=page,
        page_size=page_size,
    )
    return ListGroupMembershipsResponse(
        total=total,
        page=page,
        page_size=page_size,
        memberships=[await _to_out(m, group_service, org_service) for m in memberships],
    )


@router.get("/{membership_id}", response_model=GetGroupMembershipResponse)
async def get_group_membership(
    membership_id: uuid.UUID,
    _current_user: User = Depends(get_current_user),
    group_service: GroupService = Depends(get_group_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> GetGroupMembershipResponse:
    membership = await group_service.get_membership(membership_id)
    return GetGroupMembershipResponse(membership=await _to_out(membership, group_service, org_service))


@router.patch("/{membership_id}", response_model=UpdateGroupMembershipResponse)
async def update_group_membership(
    membership_id: uuid.UUID,
    payload: GroupMembershipUpdateRequest,
    current_user: User = Depends(get_current_user),
    group_service: GroupService = Depends(get_group_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> UpdateGroupMembershipResponse:
    membership = await group_service.get_membership(membership_id)
    await group_service.ensure_can_manage_membership(membership, current_user)

    membership = await group_service.update_membership(
        membership_id,
        role=payload.role,
        status=payload.status,
        expires_at=payload.expires_at,
        attributes=payload.attributes,
        updated_by=current_user.id,
    )
    return UpdateGroupMembershipResponse(membership=await _to_out(membership, group_service, org_service))


@router.delete("/{membership_id}", response_model=DeleteGroupMembershipResponse)
async def delete_group_membership(
    membership_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    group_service: GroupService = Depends(get_group_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> DeleteGroupMembershipResponse:
    membership = await group_service.get_membership(membership_id)
    await group_service.ensure_can_manage_membership(membership, current_user)

    await group_service.delete_membership(membership_id)
    return DeleteGroupMembershipResponse()
