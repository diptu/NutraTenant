"""Policies API (policies_api_spec) — ABAC policy CRUD, publish workflow,
and a single-policy simulate/dry-run, plus the pre-existing PDP evaluation
endpoint this spec doesn't touch.

CRUD stays superuser-only even for a tenant-scoped policy (``tenant_id``
set) — ABAC policies directly control authorization decisions, so authoring
them is deliberately *not* devolved to tenant owners the way Role/Group
management is; ``tenant_id`` is a scoping dimension a superuser sets, not a
grant of policy-authoring power to that tenant.

``POST /policies/evaluate`` is the concrete "dual RBAC-ABAC guard" the
checklist asks for: reaching it at all requires a valid JWT (the coarse
RBAC layer — see app.api.v1.dependencies.get_current_user), and the
response is the fine-grained ABAC decision for the *caller's own* identity
as subject — there is no way to evaluate access on behalf of someone else
through this endpoint. Untouched by this spec, which adds a *separate*,
single-named-policy ``/simulate`` dry-run instead.
"""

from __future__ import annotations

import uuid
from typing import cast

from app.api.v1.dependencies import get_current_user, require_superuser
from app.api.v1.policies.requests import (
    PolicyCreateRequest,
    PolicyEvaluateRequest,
    PolicyPublishRequest,
    PolicySimulateRequest,
    PolicySubjectsIn,
    PolicyUpdateRequest,
)
from app.api.v1.policies.responses import (
    CreatePolicyResponse,
    DeletePolicyResponse,
    ListPoliciesResponse,
    PolicyEvaluateResponse,
    PolicyListItemOut,
    PolicyMatchOut,
    PolicyOut,
    PolicyPaginationOut,
    PolicyPublishResponse,
    PolicySimulateResponse,
    UpdatePolicyResponse,
)
from app.core.context_middleware import get_request_context
from app.modules.organizations.dependencies import get_organization_service
from app.modules.organizations.service import OrganizationService
from app.modules.policies.dependencies import get_policy_engine_service, get_policy_service
from app.modules.policies.models import Policy
from app.modules.policies.service import PolicyEngineService, PolicyService
from app.modules.policies.value_objects import PolicyEffect, PolicyStatus, PolicyType
from app.modules.users.models import User
from fastapi import APIRouter, Depends, Query, status

router = APIRouter(prefix="/policies", tags=["policies"])


async def _resolve_organization_id(
    tenant_id: str | None, org_service: OrganizationService
) -> uuid.UUID | None:
    if tenant_id is None:
        return None
    organization = await org_service.get_by_slug(tenant_id)
    return organization.id


async def _to_out(policy: Policy, org_service: OrganizationService) -> PolicyOut:
    tenant_id = None
    if policy.organization_id is not None:
        organization = await org_service.get(policy.organization_id)
        tenant_id = organization.slug
    return PolicyOut(
        policy_id=policy.id,
        name=policy.name,
        display_name=policy.display_name,
        description=policy.description,
        type=cast(PolicyType, policy.type),
        effect=cast(PolicyEffect, policy.effect.upper()),
        status=cast(PolicyStatus, policy.status),
        priority=policy.priority,
        tenant_id=tenant_id,
        resource_types=policy.resource_types,
        actions=policy.actions,
        subjects=PolicySubjectsIn.model_validate(policy.subjects),
        conditions=policy.conditions,
        metadata=policy.extra_metadata,
        version=f"v{policy.version}",
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


@router.post("", response_model=CreatePolicyResponse, status_code=status.HTTP_201_CREATED)
async def create_policy(
    payload: PolicyCreateRequest,
    admin: User = Depends(require_superuser),
    policy_service: PolicyService = Depends(get_policy_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> CreatePolicyResponse:
    organization_id = await _resolve_organization_id(payload.tenant_id, org_service)
    policy = await policy_service.create_policy(
        name=payload.name,
        display_name=payload.display_name,
        description=payload.description,
        type=payload.type,
        status=payload.status,
        effect=payload.effect.lower(),
        priority=payload.priority,
        organization_id=organization_id,
        resource_types=payload.resource_types,
        actions=payload.actions,
        subjects=payload.subjects.model_dump(),
        conditions=payload.conditions,
        metadata=payload.metadata,
        created_by=admin.id,
    )
    return CreatePolicyResponse(
        policy_id=policy.id,
        version=f"v{policy.version}",
        status=cast(PolicyStatus, policy.status),
        created_at=policy.created_at,
    )


@router.get("", response_model=ListPoliciesResponse)
async def list_policies(
    status_: str | None = Query(default=None, alias="status"),
    type: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    _admin: User = Depends(require_superuser),
    policy_service: PolicyService = Depends(get_policy_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> ListPoliciesResponse:
    organization_id = await _resolve_organization_id(tenant_id, org_service)
    policies, total = await policy_service.list_paginated(
        status=status_,
        type=type,
        organization_id=organization_id,
        page=page,
        page_size=limit,
    )
    return ListPoliciesResponse(
        items=[
            PolicyListItemOut(
                policy_id=p.id,
                name=p.name,
                status=cast(PolicyStatus, p.status),
                priority=p.priority,
                version=f"v{p.version}",
            )
            for p in policies
        ],
        pagination=PolicyPaginationOut(page=page, limit=limit, total=total),
    )


@router.get("/{policy_id}", response_model=PolicyOut)
async def get_policy(
    policy_id: uuid.UUID,
    _admin: User = Depends(require_superuser),
    policy_service: PolicyService = Depends(get_policy_service),
    org_service: OrganizationService = Depends(get_organization_service),
) -> PolicyOut:
    policy = await policy_service.get_policy(policy_id)
    return await _to_out(policy, org_service)


@router.put("/{policy_id}", response_model=UpdatePolicyResponse)
async def update_policy(
    policy_id: uuid.UUID,
    payload: PolicyUpdateRequest,
    admin: User = Depends(require_superuser),
    policy_service: PolicyService = Depends(get_policy_service),
) -> UpdatePolicyResponse:
    fields = payload.model_fields_set
    policy = await policy_service.update_policy(
        policy_id,
        actor_id=admin.id,
        display_name=payload.display_name,
        description=payload.description,
        type=payload.type,
        status=payload.status,
        effect=payload.effect.lower() if payload.effect is not None else None,
        priority=payload.priority,
        resource_types=payload.resource_types,
        actions=payload.actions,
        subjects=payload.subjects.model_dump() if payload.subjects is not None else None,
        conditions=payload.conditions,
        update_conditions="conditions" in fields,
        metadata=payload.metadata,
    )
    return UpdatePolicyResponse(
        policy_id=policy.id, version=f"v{policy.version}", updated_at=policy.updated_at
    )


@router.post("/{policy_id}/publish", response_model=PolicyPublishResponse)
async def publish_policy(
    policy_id: uuid.UUID,
    payload: PolicyPublishRequest,
    admin: User = Depends(require_superuser),
    policy_service: PolicyService = Depends(get_policy_service),
) -> PolicyPublishResponse:
    policy = await policy_service.publish_policy(policy_id, actor_id=admin.id, comment=payload.comment)
    return PolicyPublishResponse(
        policy_id=policy.id, version=f"v{policy.version}", status=cast(PolicyStatus, policy.status)
    )


@router.post("/{policy_id}/simulate", response_model=PolicySimulateResponse)
async def simulate_policy(
    policy_id: uuid.UUID,
    payload: PolicySimulateRequest,
    _admin: User = Depends(require_superuser),
    policy_service: PolicyService = Depends(get_policy_service),
    policy_engine: PolicyEngineService = Depends(get_policy_engine_service),
) -> PolicySimulateResponse:
    policy = await policy_service.get_policy(policy_id)
    result = policy_engine.simulate(
        policy,
        subject=payload.subject,
        resource=payload.resource,
        action=payload.action,
        context=payload.context,
    )
    return PolicySimulateResponse(
        decision=cast(PolicyEffect, result.decision.upper()),
        matched_policy=policy.id,
        matched_rules=result.matched_rules,
        evaluation_id=result.evaluation_id,
    )


@router.delete("/{policy_id}", response_model=DeletePolicyResponse)
async def delete_policy(
    policy_id: uuid.UUID,
    admin: User = Depends(require_superuser),
    policy_service: PolicyService = Depends(get_policy_service),
) -> DeletePolicyResponse:
    await policy_service.delete_policy(policy_id, actor_id=admin.id)
    return DeletePolicyResponse()


@router.post("/evaluate", response_model=PolicyEvaluateResponse)
async def evaluate_policy(
    payload: PolicyEvaluateRequest,
    current_user: User = Depends(get_current_user),
    context: dict = Depends(get_request_context),
    policy_engine: PolicyEngineService = Depends(get_policy_engine_service),
) -> PolicyEvaluateResponse:
    result = await policy_engine.evaluate(
        subject=current_user,
        resource_type=payload.resource_type,
        action=payload.action,
        resource_id=payload.resource_id,
        resource_attributes=payload.resource_attributes,
        context=context,
    )
    return PolicyEvaluateResponse(
        decision=result.decision,  # type: ignore[arg-type]
        matched_policies=[
            PolicyMatchOut(
                policy_id=m.policy_id,
                policy_name=m.policy_name,
                effect=m.effect,
                matched=m.matched,
                reason=m.reason,
            )
            for m in result.matched_policies
        ],
        context=result.context_snapshot,
        log_id=result.log_id,
    )
