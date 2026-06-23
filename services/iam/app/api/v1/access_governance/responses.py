"""Response models for /api/v1/access-requests, /access-reviews,
and /access-approvals (User and Access APIs Specification)."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.modules.access_governance.value_objects import AccessApprovalDecision, AccessRequestStatus
from pydantic import BaseModel


class CreateAccessRequestResponse(BaseModel):
    request_id: uuid.UUID
    status: AccessRequestStatus


class AccessRequestOut(BaseModel):
    request_id: uuid.UUID
    user_id: uuid.UUID
    requested_roles: list[str]
    requested_permissions: list[str]
    justification: str | None
    status: AccessRequestStatus
    created_at: datetime
    updated_at: datetime


class CreateAccessReviewResponse(BaseModel):
    review_id: uuid.UUID
    status: str


class AccessReviewOut(BaseModel):
    review_id: uuid.UUID
    review_scope: str
    tenant_id: str | None
    review_type: str
    status: str
    created_at: datetime
    updated_at: datetime


class CreateAccessApprovalResponse(BaseModel):
    approval_id: uuid.UUID
    status: str
    processed_at: datetime


class AccessApprovalOut(BaseModel):
    approval_id: uuid.UUID
    request_id: uuid.UUID
    decision: AccessApprovalDecision
    comment: str | None
    status: str
    processed_at: datetime
    created_at: datetime
