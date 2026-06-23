"""/api/v1/access-requests, /access-reviews, /access-approvals (User and
Access APIs Specification) — access governance tracking. See
app.modules.access_governance.service for why approving a request never
mutates a user's actual roles/permissions.

Matches the spec literally: only create + get-by-id exist for each of the
three sub-resources — no list/update/delete endpoints are defined there.
"""

from __future__ import annotations

import uuid

from app.api.v1.access_governance.requests import (
    AccessApprovalCreateRequest,
    AccessRequestCreateRequest,
    AccessReviewCreateRequest,
)
from app.api.v1.access_governance.responses import (
    AccessApprovalOut,
    AccessRequestOut,
    AccessReviewOut,
    CreateAccessApprovalResponse,
    CreateAccessRequestResponse,
    CreateAccessReviewResponse,
)
from app.api.v1.dependencies import get_current_user, require_superuser
from app.domain.exceptions import ForbiddenError
from app.modules.access_governance.dependencies import get_access_governance_service
from app.modules.access_governance.models import AccessRequest
from app.modules.access_governance.service import AccessGovernanceService
from app.modules.organizations.dependencies import get_organization_service
from app.modules.organizations.service import OrganizationService
from app.modules.users.models import User
from fastapi import APIRouter, Depends, status

access_requests_router = APIRouter(prefix="/access-requests", tags=["access-requests"])
access_reviews_router = APIRouter(prefix="/access-reviews", tags=["access-reviews"])
access_approvals_router = APIRouter(prefix="/access-approvals", tags=["access-approvals"])


def _to_request_out(request: AccessRequest) -> AccessRequestOut:
    return AccessRequestOut(
        request_id=request.id,
        user_id=request.user_id,
        requested_roles=request.requested_roles,
        requested_permissions=request.requested_permissions,
        justification=request.justification,
        status=request.status,  # type: ignore[arg-type]
        created_at=request.created_at,
        updated_at=request.updated_at,
    )


@access_requests_router.post(
    "", response_model=CreateAccessRequestResponse, status_code=status.HTTP_201_CREATED
)
async def create_access_request(
    payload: AccessRequestCreateRequest,
    current_user: User = Depends(get_current_user),
    access_governance: AccessGovernanceService = Depends(get_access_governance_service),
) -> CreateAccessRequestResponse:
    """Any authenticated user may file a request for themselves; filing one
    on someone else's behalf requires a superuser."""
    if current_user.id != payload.user_id and not current_user.is_superuser:
        raise ForbiddenError("You can only file an access request for yourself")

    request = await access_governance.create_request(
        user_id=payload.user_id,
        requested_roles=payload.requested_roles,
        requested_permissions=payload.requested_permissions,
        justification=payload.justification,
        requested_by=current_user.id,
    )
    return CreateAccessRequestResponse(request_id=request.id, status=request.status)  # type: ignore[arg-type]


@access_requests_router.get("/{request_id}", response_model=AccessRequestOut)
async def get_access_request(
    request_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    access_governance: AccessGovernanceService = Depends(get_access_governance_service),
) -> AccessRequestOut:
    request = await access_governance.get_request(request_id)
    if current_user.id != request.user_id and not current_user.is_superuser:
        raise ForbiddenError("You can only view your own access requests")
    return _to_request_out(request)


@access_reviews_router.post(
    "", response_model=CreateAccessReviewResponse, status_code=status.HTTP_201_CREATED
)
async def create_access_review(
    payload: AccessReviewCreateRequest,
    admin: User = Depends(require_superuser),
    access_governance: AccessGovernanceService = Depends(get_access_governance_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> CreateAccessReviewResponse:
    organization_id = None
    if payload.tenant_id is not None:
        organization = await org_service.get_by_slug(payload.tenant_id)
        organization_id = organization.id

    review = await access_governance.create_review(
        review_scope=payload.review_scope,
        organization_id=organization_id,
        review_type=payload.review_type,
        created_by=admin.id,
    )
    return CreateAccessReviewResponse(review_id=review.id, status=review.status)


@access_reviews_router.get("/{review_id}", response_model=AccessReviewOut)
async def get_access_review(
    review_id: uuid.UUID,
    _admin: User = Depends(require_superuser),
    access_governance: AccessGovernanceService = Depends(get_access_governance_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> AccessReviewOut:
    review = await access_governance.get_review(review_id)
    tenant_id = None
    if review.organization_id is not None:
        organization = await org_service.get(review.organization_id)
        tenant_id = organization.slug
    return AccessReviewOut(
        review_id=review.id,
        review_scope=review.review_scope,
        tenant_id=tenant_id,
        review_type=review.review_type,
        status=review.status,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


@access_approvals_router.post(
    "", response_model=CreateAccessApprovalResponse, status_code=status.HTTP_201_CREATED
)
async def create_access_approval(
    payload: AccessApprovalCreateRequest,
    admin: User = Depends(require_superuser),
    access_governance: AccessGovernanceService = Depends(get_access_governance_service),
) -> CreateAccessApprovalResponse:
    approval = await access_governance.create_approval(
        request_id=payload.request_id,
        decision=payload.decision,
        comment=payload.comment,
        processed_by=admin.id,
    )
    return CreateAccessApprovalResponse(
        approval_id=approval.id, status=approval.status, processed_at=approval.processed_at
    )


@access_approvals_router.get("/{approval_id}", response_model=AccessApprovalOut)
async def get_access_approval(
    approval_id: uuid.UUID,
    _admin: User = Depends(require_superuser),
    access_governance: AccessGovernanceService = Depends(get_access_governance_service),
) -> AccessApprovalOut:
    approval = await access_governance.get_approval(approval_id)
    return AccessApprovalOut(
        approval_id=approval.id,
        request_id=approval.access_request_id,
        decision=approval.decision,  # type: ignore[arg-type]
        comment=approval.comment,
        status=approval.status,
        processed_at=approval.processed_at,
        created_at=approval.created_at,
    )
