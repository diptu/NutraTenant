"""Request bodies for the Policies API (policies_api_spec) and the
pre-existing PDP evaluation endpoint."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from app.modules.policies.value_objects import PolicyEffect, PolicyStatus, PolicyType
from pydantic import BaseModel, Field


class PolicySubjectsIn(BaseModel):
    roles: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    users: list[str] = Field(default_factory=list)


class PolicyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    type: PolicyType = "ABAC"
    status: PolicyStatus = "ACTIVE"
    # Purely a documentation/consistency convenience on the wire — the
    # actual scope is always derived from tenant_id (None => global).
    tenant_scope: Literal["global", "tenant"] | None = None
    tenant_id: str | None = None
    priority: int = 0
    effect: PolicyEffect
    resource_types: list[str] = Field(min_length=1)
    actions: list[str] = Field(min_length=1)
    subjects: PolicySubjectsIn = Field(default_factory=PolicySubjectsIn)
    conditions: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyUpdateRequest(BaseModel):
    display_name: str | None = None
    description: str | None = None
    type: PolicyType | None = None
    status: PolicyStatus | None = None
    priority: int | None = None
    effect: PolicyEffect | None = None
    resource_types: list[str] | None = Field(default=None, min_length=1)
    actions: list[str] | None = Field(default=None, min_length=1)
    subjects: PolicySubjectsIn | None = None
    conditions: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class PolicyPublishRequest(BaseModel):
    comment: str | None = None


class PolicySimulateRequest(BaseModel):
    """A synthetic subject/resource/context dry-run against one named
    policy — ``subject``/``resource``/``context`` are free-form (a
    simulated subject needn't be a real registered user; see
    app.modules.policies.service.PolicyEngineService.simulate)."""

    subject: dict[str, Any] = Field(default_factory=dict)
    resource: dict[str, Any] = Field(default_factory=dict)
    action: str = Field(min_length=1, max_length=200)
    context: dict[str, Any] = Field(default_factory=dict)


# -- pre-existing PDP evaluation endpoint (POST /policies/evaluate) ---------
# Untouched by policies_api_spec — evaluates the full policy catalog (not
# one named policy) for the *caller's own* identity. Kept in its original
# lowercase "allow"/"deny" shape since it's a separate, already-shipped
# contract this spec doesn't define.


class PolicyEvaluateRequest(BaseModel):
    resource_type: str = Field(min_length=1, max_length=100)
    action: str = Field(min_length=1, max_length=100)
    resource_id: uuid.UUID | None = None
    resource_attributes: dict[str, Any] = Field(default_factory=dict)
