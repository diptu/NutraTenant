"""Response models for the Policies API (policies_api_spec) and the
pre-existing PDP evaluation endpoint.

Responses here are deliberately *not* wrapped in a ``{"policy": {...}}``
envelope (unlike Role/Permission/Group's "Common Object" responses) — the
spec's own examples return the object directly at every endpoint, with a
distinct, smaller shape per endpoint (a full object on Get, a slim
``{policy_id, version, status, ...}`` receipt on Create/Update/Publish, and
a slimmer-still list item on List) — that's honored literally rather than
normalized to one shared shape.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from app.api.v1.policies.requests import PolicySubjectsIn
from app.modules.policies.value_objects import PolicyEffect, PolicyStatus, PolicyType
from pydantic import BaseModel


class PolicyOut(BaseModel):
    """The Common Policy Object — backs ``GET /policies/{policy_id}``."""

    policy_id: uuid.UUID
    name: str
    display_name: str | None
    description: str | None
    type: PolicyType
    effect: PolicyEffect
    status: PolicyStatus
    priority: int
    tenant_id: str | None
    resource_types: list[str]
    actions: list[str]
    subjects: PolicySubjectsIn
    conditions: dict[str, Any] | None
    metadata: dict[str, Any]
    version: str
    created_at: datetime
    updated_at: datetime


class CreatePolicyResponse(BaseModel):
    policy_id: uuid.UUID
    version: str
    status: PolicyStatus
    created_at: datetime


class UpdatePolicyResponse(BaseModel):
    policy_id: uuid.UUID
    version: str
    updated_at: datetime


class PolicyListItemOut(BaseModel):
    policy_id: uuid.UUID
    name: str
    status: PolicyStatus
    priority: int
    version: str


class PolicyPaginationOut(BaseModel):
    page: int
    limit: int
    total: int


class ListPoliciesResponse(BaseModel):
    items: list[PolicyListItemOut]
    pagination: PolicyPaginationOut


class PolicyPublishResponse(BaseModel):
    policy_id: uuid.UUID
    version: str
    status: PolicyStatus


class DeletePolicyResponse(BaseModel):
    success: bool = True
    message: str = "Policy deleted"


class PolicySimulateResponse(BaseModel):
    decision: PolicyEffect
    matched_policy: uuid.UUID
    matched_rules: list[str]
    evaluation_id: uuid.UUID


class PolicyMatchOut(BaseModel):
    policy_id: uuid.UUID
    policy_name: str
    effect: str
    matched: bool
    reason: str


class PolicyEvaluateResponse(BaseModel):
    decision: Literal["allow", "deny"]
    matched_policies: list[PolicyMatchOut]
    context: dict[str, Any]
    log_id: uuid.UUID | None
