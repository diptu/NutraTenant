"""ABAC policy CRUD + publish workflow — the "Fine-Grained Layer" management
surface (policies_api_spec) — plus the Policy Decision Point (PDP):
deterministic ABAC evaluation with deny-overrides conflict resolution.

PolicyService validates ``conditions`` structurally at write time (see
app.modules.policies.policy_conditions) so a malformed rule is rejected
here, not discovered mid-evaluation by the PDP for some unrelated request.
``effect`` is validated/stored lowercase internally — the API's uppercase
``ALLOW``/``DENY`` wire format is translated at the route layer, see
app.modules.policies.models.

PolicyEngineService is the PDP itself — see
app.modules.policies.use_cases.evaluate_policy for the matching algorithm.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.audit import AuditLogRepository
from app.modules.policies.exceptions import PolicyNotFoundError
from app.modules.policies.models import Policy
from app.modules.policies.repositories.sqlalchemy.policy_evaluation_log_repository import (
    PolicyEvaluationLogRepository,
)
from app.modules.policies.repositories.sqlalchemy.policy_repository import PolicyRepository
from app.modules.policies.schemas.commands.create_policy_command import CreatePolicyCommand
from app.modules.policies.schemas.commands.delete_policy_command import DeletePolicyCommand
from app.modules.policies.schemas.commands.publish_policy_command import PublishPolicyCommand
from app.modules.policies.schemas.commands.update_policy_command import UpdatePolicyCommand
from app.modules.policies.schemas.dto.pdp_result_dto import PDPResult
from app.modules.policies.schemas.dto.simulation_result_dto import SimulationResult
from app.modules.policies.schemas.queries.evaluate_policy_query import EvaluatePolicyQuery
from app.modules.policies.schemas.queries.simulate_policy_query import SimulatePolicyQuery
from app.modules.policies.use_cases.create_policy import CreatePolicyUseCase
from app.modules.policies.use_cases.delete_policy import DeletePolicyUseCase
from app.modules.policies.use_cases.evaluate_policy import EvaluatePolicyUseCase
from app.modules.policies.use_cases.publish_policy import PublishPolicyUseCase
from app.modules.policies.use_cases.simulate_policy import SimulatePolicyUseCase
from app.modules.policies.use_cases.update_policy import UpdatePolicyUseCase
from app.modules.users.models import User


class PolicyService:
    def __init__(self, session) -> None:
        self._session = session
        self._policies = PolicyRepository(session)
        self._audit_log = AuditLogRepository(session)
        self._create_use_case = CreatePolicyUseCase(session, self._policies, self._audit_log)
        self._update_use_case = UpdatePolicyUseCase(session, self._policies, self._audit_log)
        self._publish_use_case = PublishPolicyUseCase(session, self._policies, self._audit_log)
        self._delete_use_case = DeletePolicyUseCase(session, self._policies, self._audit_log)

    async def list_paginated(
        self,
        *,
        status: str | None,
        type: str | None,
        organization_id: uuid.UUID | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Policy], int]:
        offset = (page - 1) * page_size
        return await self._policies.search_catalog(
            status=status,
            type=type,
            organization_id=organization_id,
            limit=page_size,
            offset=offset,
        )

    async def get_policy(self, policy_id: uuid.UUID) -> Policy:
        policy = await self._policies.get_by_id(policy_id)
        if policy is None:
            raise PolicyNotFoundError(f"No policy with id '{policy_id}'")
        return policy

    async def create_policy(
        self,
        *,
        name: str,
        display_name: str | None,
        description: str | None,
        type: str,
        status: str,
        effect: str,
        priority: int,
        organization_id: uuid.UUID | None,
        resource_types: list[str],
        actions: list[str],
        subjects: dict,
        conditions: dict | None,
        metadata: dict,
        created_by: uuid.UUID,
    ) -> Policy:
        command = CreatePolicyCommand(
            name=name,
            display_name=display_name,
            description=description,
            type=type,
            status=status,
            effect=effect,
            priority=priority,
            organization_id=organization_id,
            resource_types=resource_types,
            actions=actions,
            subjects=subjects,
            conditions=conditions,
            metadata=metadata,
            created_by=created_by,
        )
        return await self._create_use_case.execute(command)

    async def update_policy(
        self,
        policy_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        display_name: str | None = None,
        description: str | None = None,
        type: str | None = None,
        status: str | None = None,
        effect: str | None = None,
        priority: int | None = None,
        resource_types: list[str] | None = None,
        actions: list[str] | None = None,
        subjects: dict | None = None,
        conditions: dict | None = None,
        update_conditions: bool = False,
        metadata: dict | None = None,
    ) -> Policy:
        command = UpdatePolicyCommand(
            policy_id=policy_id,
            actor_id=actor_id,
            display_name=display_name,
            description=description,
            type=type,
            status=status,
            effect=effect,
            priority=priority,
            resource_types=resource_types,
            actions=actions,
            subjects=subjects,
            conditions=conditions,
            update_conditions=update_conditions,
            metadata=metadata,
        )
        return await self._update_use_case.execute(command)

    async def publish_policy(
        self, policy_id: uuid.UUID, *, actor_id: uuid.UUID, comment: str | None
    ) -> Policy:
        command = PublishPolicyCommand(policy_id=policy_id, actor_id=actor_id, comment=comment)
        return await self._publish_use_case.execute(command)

    async def delete_policy(self, policy_id: uuid.UUID, *, actor_id: uuid.UUID) -> None:
        command = DeletePolicyCommand(policy_id=policy_id, actor_id=actor_id)
        await self._delete_use_case.execute(command)


class PolicyEngineService:
    def __init__(self, session) -> None:
        self._session = session
        self._policies = PolicyRepository(session)
        self._logs = PolicyEvaluationLogRepository(session)
        self._evaluate_use_case = EvaluatePolicyUseCase(session, self._policies, self._logs)
        self._simulate_use_case = SimulatePolicyUseCase()

    async def evaluate(
        self,
        *,
        subject: User,
        resource_type: str,
        action: str,
        resource_id: uuid.UUID | None = None,
        resource_attributes: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        organization_id: uuid.UUID | None = None,
    ) -> PDPResult:
        query = EvaluatePolicyQuery(
            subject=subject,
            resource_type=resource_type,
            action=action,
            resource_id=resource_id,
            resource_attributes=resource_attributes,
            context=context,
            organization_id=organization_id,
        )
        return await self._evaluate_use_case.execute(query)

    def simulate(
        self,
        policy: Policy,
        *,
        subject: dict[str, Any],
        resource: dict[str, Any],
        action: str,
        context: dict[str, Any] | None = None,
    ) -> SimulationResult:
        query = SimulatePolicyQuery(
            policy=policy, subject=subject, resource=resource, action=action, context=context
        )
        return self._simulate_use_case.execute(query)
