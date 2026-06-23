"""Request bodies for /api/v1/access-requests, /access-reviews,
and /access-approvals (User and Access APIs Specification)."""

from __future__ import annotations

import uuid

from app.modules.access_governance.value_objects import AccessApprovalDecision
from pydantic import BaseModel, Field


class AccessRequestCreateRequest(BaseModel):
    user_id: uuid.UUID
    requested_roles: list[str] = Field(default_factory=list)
    requested_permissions: list[str] = Field(default_factory=list)
    justification: str | None = Field(default=None, max_length=2000)


class AccessReviewCreateRequest(BaseModel):
    review_scope: str = Field(min_length=1, max_length=20)
    tenant_id: str | None = None
    review_type: str = Field(min_length=1, max_length=50)


class AccessApprovalCreateRequest(BaseModel):
    request_id: uuid.UUID
    decision: AccessApprovalDecision
    comment: str | None = Field(default=None, max_length=2000)
