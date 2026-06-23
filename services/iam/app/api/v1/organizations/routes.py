"""Organization lifecycle and membership management."""

from __future__ import annotations

import uuid

from app.api.v1.dependencies import get_current_user, require_superuser
from app.api.v1.organizations.requests import (
    AcceptInvitationRequest,
    AddMemberRequest,
    InviteMemberRequest,
    OrganizationCreateRequest,
    OrganizationUpdateRequest,
    UpdateMemberRoleRequest,
)
from app.api.v1.organizations.responses import (
    InvitationOut,
    OrganizationMemberOut,
    OrganizationOut,
)
from app.modules.organizations.dependencies import get_organization_service
from app.modules.organizations.service import OrganizationService
from app.modules.users.models import User
from app.shared.exceptions.base import ForbiddenError
from fastapi import APIRouter, Depends, status

router = APIRouter(prefix="/organizations", tags=["organizations"])


async def _ensure_owner_or_superuser(
    org_service: OrganizationService, organization_id: uuid.UUID, current_user: User
) -> None:
    await org_service.get(organization_id)  # 404s first if the org doesn't exist at all
    if current_user.is_superuser:
        return
    await org_service.require_owner(organization_id, current_user.id)


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrganizationCreateRequest,
    current_user: User = Depends(require_superuser),
    org_service: OrganizationService = Depends(get_organization_service),
) -> OrganizationOut:
    """Superuser-only — tenant/organization creation is platform-provisioned,
    not self-service. See also POST /api/v1/tenants for the richer
    enterprise-onboarding contract (settings/metadata, owner-email bootstrap)
    over the same underlying creation path."""
    org = await org_service.create(
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        owner_id=current_user.id,
    )
    return OrganizationOut.model_validate(org)


@router.get("", response_model=list[OrganizationOut])
async def list_my_organizations(
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_organization_service),
) -> list[OrganizationOut]:
    orgs = await org_service.list_for_user(current_user.id)
    return [OrganizationOut.model_validate(o) for o in orgs]


@router.get("/{organization_id}", response_model=OrganizationOut)
async def get_organization(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_organization_service),
) -> OrganizationOut:
    # Existence first: a nonexistent org must 404, not 403 — checking
    # membership first means "no such org" and "no such org_id" look
    # identical (no membership row in either case), which leaked as a
    # wrong 403 here previously.
    org = await org_service.get(organization_id)
    if not current_user.is_superuser:
        await org_service.require_membership(organization_id, current_user.id)
    return OrganizationOut.model_validate(org)


@router.patch("/{organization_id}", response_model=OrganizationOut)
async def update_organization(
    organization_id: uuid.UUID,
    payload: OrganizationUpdateRequest,
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_organization_service),
) -> OrganizationOut:
    await _ensure_owner_or_superuser(org_service, organization_id, current_user)
    if payload.is_reserved is not None and not current_user.is_superuser:
        raise ForbiddenError("Only a superuser can change an organization's reserved flag")
    org = await org_service.update(
        organization_id,
        name=payload.name,
        description=payload.description,
        default_attributes=payload.default_attributes,
        is_reserved=payload.is_reserved,
    )
    return OrganizationOut.model_validate(org)


@router.delete("/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_organization_service),
) -> None:
    await _ensure_owner_or_superuser(org_service, organization_id, current_user)
    await org_service.delete(organization_id)


@router.get("/{organization_id}/members", response_model=list[OrganizationMemberOut])
async def list_organization_members(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_organization_service),
) -> list[OrganizationMemberOut]:
    members = await org_service.list_members(organization_id)  # 404s first if missing
    if not current_user.is_superuser:
        await org_service.require_membership(organization_id, current_user.id)
    return [
        OrganizationMemberOut(user_id=m.user_id, role_code=m.role.code, is_active=m.is_active)
        for m in members
    ]


@router.post(
    "/{organization_id}/members",
    response_model=OrganizationMemberOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_organization_member(
    organization_id: uuid.UUID,
    payload: AddMemberRequest,
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_organization_service),
) -> OrganizationMemberOut:
    await _ensure_owner_or_superuser(org_service, organization_id, current_user)
    membership = await org_service.add_member(
        organization_id,
        user_id=payload.user_id,
        role_code=payload.role_code,
        invited_by=current_user.id,
    )
    return OrganizationMemberOut(
        user_id=membership.user_id,
        role_code=payload.role_code,
        is_active=membership.is_active,
    )


@router.delete("/{organization_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_organization_member(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_organization_service),
) -> None:
    # A member may always remove *themself* (leaving the org); removing
    # someone else requires being the owner or a superuser.
    if user_id != current_user.id:
        await _ensure_owner_or_superuser(org_service, organization_id, current_user)
    await org_service.remove_member(organization_id, user_id, actor_id=current_user.id)


@router.patch("/{organization_id}/members/{user_id}", response_model=OrganizationMemberOut)
async def update_organization_member_role(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: UpdateMemberRoleRequest,
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_organization_service),
) -> OrganizationMemberOut:
    """Open to any member, not just the owner — OrganizationService applies
    the privilege-escalation guard (can't grant a role exceeding your own
    permissions, and only the owner can grant ownership) and the
    last-owner-can't-be-demoted protection."""
    if not current_user.is_superuser:
        await org_service.require_membership(organization_id, current_user.id)
    membership = await org_service.update_member_role(
        organization_id,
        user_id,
        new_role_code=payload.role_code,
        actor_id=current_user.id,
    )
    return OrganizationMemberOut(
        user_id=membership.user_id,
        role_code=membership.role.code,
        is_active=membership.is_active,
    )


@router.post(
    "/{organization_id}/invitations",
    response_model=InvitationOut,
    status_code=status.HTTP_201_CREATED,
)
async def invite_organization_member(
    organization_id: uuid.UUID,
    payload: InviteMemberRequest,
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_organization_service),
) -> InvitationOut:
    await _ensure_owner_or_superuser(org_service, organization_id, current_user)
    invitation, raw_token = await org_service.invite_member(
        organization_id,
        email=payload.email,
        role_code=payload.role_code,
        invited_by=current_user.id,
    )
    return InvitationOut(
        id=invitation.id,
        organization_id=invitation.organization_id,
        email=invitation.email,
        role_code=invitation.role_code,
        expires_at=invitation.expires_at,
        invitation_token=raw_token,
    )


@router.get("/{organization_id}/invitations", response_model=list[InvitationOut])
async def list_organization_invitations(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_organization_service),
) -> list[InvitationOut]:
    await _ensure_owner_or_superuser(org_service, organization_id, current_user)
    invitations = await org_service.list_pending_invitations(organization_id)
    return [
        InvitationOut(
            id=inv.id,
            organization_id=inv.organization_id,
            email=inv.email,
            role_code=inv.role_code,
            expires_at=inv.expires_at,
        )
        for inv in invitations
    ]


@router.delete(
    "/{organization_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_organization_invitation(
    organization_id: uuid.UUID,
    invitation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_organization_service),
) -> None:
    await _ensure_owner_or_superuser(org_service, organization_id, current_user)
    await org_service.revoke_invitation(organization_id, invitation_id)


@router.post("/invitations/accept", response_model=OrganizationMemberOut)
async def accept_organization_invitation(
    payload: AcceptInvitationRequest,
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_organization_service),
) -> OrganizationMemberOut:
    membership, role_code = await org_service.accept_invitation(
        raw_token=payload.token,
        accepting_user_id=current_user.id,
        accepting_email=current_user.email,
    )
    return OrganizationMemberOut(
        user_id=membership.user_id,
        role_code=role_code,
        is_active=membership.is_active,
    )
