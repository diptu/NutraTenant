"""ABAC policy CRUD (admin-only) and the PDP evaluation endpoint.

``POST /policies/evaluate`` is the concrete "dual RBAC-ABAC guard" the
checklist asks for: reaching it at all requires a valid JWT (the coarse
RBAC layer — see app.api.v1.dependencies.get_current_user), and the
response is the fine-grained ABAC decision for the *caller's own* identity
as subject — there is no way to evaluate access on behalf of someone else
through this endpoint.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.api.v1.dependencies import (
    get_current_user,
    get_policy_engine_service,
    get_policy_service,
    require_superuser,
)
from app.api.v1.schemas.policy import (
    PolicyCreateRequest,
    PolicyEvaluateRequest,
    PolicyEvaluateResponse,
    PolicyMatchOut,
    PolicyOut,
    PolicyUpdateRequest,
)
from app.core.context_middleware import get_request_context
from app.infrastructure.db.models.user import User
from app.services.policy_engine_service import PolicyEngineService
from app.services.policy_service import PolicyService

router = APIRouter(prefix="/policies", tags=["policies"])


@router.post("", response_model=PolicyOut, status_code=status.HTTP_201_CREATED)
async def create_policy(
    payload: PolicyCreateRequest,
    admin: User = Depends(require_superuser),
    policy_service: PolicyService = Depends(get_policy_service),
) -> PolicyOut:
    policy = await policy_service.create_policy(
        name=payload.name,
        description=payload.description,
        effect=payload.effect,
        resource=payload.resource,
        action=payload.action,
        conditions=payload.conditions,
        created_by=admin.id,
    )
    return PolicyOut.model_validate(policy)


@router.get("", response_model=list[PolicyOut])
async def list_policies(
    _admin: User = Depends(require_superuser),
    policy_service: PolicyService = Depends(get_policy_service),
) -> list[PolicyOut]:
    policies = await policy_service.list_policies()
    return [PolicyOut.model_validate(p) for p in policies]


@router.get("/{policy_id}", response_model=PolicyOut)
async def get_policy(
    policy_id: uuid.UUID,
    _admin: User = Depends(require_superuser),
    policy_service: PolicyService = Depends(get_policy_service),
) -> PolicyOut:
    policy = await policy_service.get_policy(policy_id)
    return PolicyOut.model_validate(policy)


@router.patch("/{policy_id}", response_model=PolicyOut)
async def update_policy(
    policy_id: uuid.UUID,
    payload: PolicyUpdateRequest,
    admin: User = Depends(require_superuser),
    policy_service: PolicyService = Depends(get_policy_service),
) -> PolicyOut:
    policy = await policy_service.update_policy(
        policy_id,
        actor_id=admin.id,
        description=payload.description,
        effect=payload.effect,
        conditions=payload.conditions,
        update_conditions="conditions" in payload.model_fields_set,
        is_active=payload.is_active,
    )
    return PolicyOut.model_validate(policy)


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(
    policy_id: uuid.UUID,
    admin: User = Depends(require_superuser),
    policy_service: PolicyService = Depends(get_policy_service),
) -> None:
    await policy_service.delete_policy(policy_id, actor_id=admin.id)


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
