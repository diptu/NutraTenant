"""Request/response models for ABAC policy management and PDP evaluation."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PolicyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    effect: Literal["allow", "deny"]
    resource: str = Field(min_length=1, max_length=100)
    action: str = Field(min_length=1, max_length=100)
    conditions: dict[str, Any] | None = None


class PolicyUpdateRequest(BaseModel):
    description: str | None = None
    effect: Literal["allow", "deny"] | None = None
    conditions: dict[str, Any] | None = None
    is_active: bool | None = None


class PolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    effect: str
    resource: str
    action: str
    conditions: dict[str, Any] | None
    version: int
    is_active: bool
    created_by: uuid.UUID | None


class PolicyEvaluateRequest(BaseModel):
    resource_type: str = Field(min_length=1, max_length=100)
    action: str = Field(min_length=1, max_length=100)
    resource_id: uuid.UUID | None = None
    resource_attributes: dict[str, Any] = Field(default_factory=dict)


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
