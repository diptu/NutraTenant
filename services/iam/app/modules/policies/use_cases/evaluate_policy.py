from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.modules.policies.models import PolicyEvaluationLog
from app.modules.policies.repositories.interfaces.policy_evaluation_log_repository import (
    PolicyEvaluationLogRepository,
)
from app.modules.policies.repositories.interfaces.policy_repository import PolicyRepository
from app.modules.policies.schemas.dto.pdp_result_dto import PDPResult, PolicyMatchResult
from app.modules.policies.schemas.queries.evaluate_policy_query import EvaluatePolicyQuery
from app.modules.policies.use_cases._matching import match_one
from sqlalchemy.ext.asyncio import AsyncSession

_logger = get_logger("abac.pdp")


class EvaluatePolicyUseCase:
    """The PDP's core algorithm:
      1. Pull the candidate set: active policies whose resource/action match
         (exactly, or via the ``*`` wildcard) — see PolicyRepository.list_matching.
      2. For each candidate, evaluate its ``conditions`` tree (None = matches
         unconditionally) against {subject, resource, action, context}.
      3. Conflict resolution is deny-overrides: any matched "deny" policy wins
         outright, regardless of how many "allow" policies also matched.
      4. No policy matched at all -> default deny (secure by default, never
         fail open).

    Every evaluation is persisted (PolicyEvaluationLog) *and* emitted as a
    structured JSON log line — the "why did this fail" trail.
    """

    def __init__(
        self,
        session: AsyncSession,
        policies: PolicyRepository,
        logs: PolicyEvaluationLogRepository,
    ) -> None:
        self._session = session
        self._policies = policies
        self._logs = logs

    async def execute(self, query: EvaluatePolicyQuery) -> PDPResult:
        """``organization_id`` defaults to ``None`` — the candidate set is
        then global policies only, exactly today's behavior (the existing
        ``POST /policies/evaluate`` route never passes it). Pass the
        subject's current tenant to also consider that tenant's scoped
        policies — see PolicyRepository.list_matching."""
        candidates = await self._policies.list_matching(
            query.resource_type, query.action, organization_id=query.organization_id
        )

        subject_snapshot = {
            "id": str(query.subject.id),
            "email": query.subject.email,
            "is_superuser": query.subject.is_superuser,
            "attributes": query.subject.attributes or {},
        }
        resource_snapshot: dict[str, Any] = {
            "type": query.resource_type,
            "id": str(query.resource_id) if query.resource_id else None,
            **(query.resource_attributes or {}),
        }
        context_snapshot = query.context or {}

        eval_context = {
            "subject": subject_snapshot,
            "resource": resource_snapshot,
            "action": query.action,
            "context": context_snapshot,
        }

        matches = [match_one(policy, eval_context) for policy in candidates]

        deny_matched = any(m.matched and m.effect == "deny" for m in matches)
        allow_matched = any(m.matched and m.effect == "allow" for m in matches)
        if deny_matched:
            decision = "deny"
        elif allow_matched:
            decision = "allow"
        else:
            decision = "deny"  # default-deny: no matching policy is not implicit access

        log_id = await self._record(
            subject_id=query.subject.id,
            resource_type=query.resource_type,
            resource_id=query.resource_id,
            action=query.action,
            decision=decision,
            matches=matches,
            subject_snapshot=subject_snapshot,
            resource_snapshot=resource_snapshot,
            context_snapshot=context_snapshot,
        )

        return PDPResult(
            decision=decision,
            matched_policies=matches,
            subject_snapshot=subject_snapshot,
            resource_snapshot=resource_snapshot,
            context_snapshot=context_snapshot,
            log_id=log_id,
        )

    async def _record(
        self,
        *,
        subject_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID | None,
        action: str,
        decision: str,
        matches: list[PolicyMatchResult],
        subject_snapshot: dict[str, Any],
        resource_snapshot: dict[str, Any],
        context_snapshot: dict[str, Any],
    ) -> uuid.UUID:
        log_id = uuid.uuid4()
        matched_payload = [m.as_dict() for m in matches]

        self._logs.add(
            PolicyEvaluationLog(
                id=log_id,
                user_id=subject_id,
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                decision=decision,
                matched_policies=matched_payload,
                subject_snapshot=subject_snapshot,
                resource_snapshot=resource_snapshot,
                context_snapshot=context_snapshot,
                evaluated_at=datetime.now(UTC),
            )
        )
        await self._session.commit()

        _logger.info(
            "abac policy evaluation",
            extra={
                "event": "abac.policy_evaluation",
                "log_id": str(log_id),
                "subject_id": str(subject_id),
                "resource_type": resource_type,
                "resource_id": str(resource_id) if resource_id else None,
                "action": action,
                "decision": decision,
                "matched_policies": matched_payload,
                "context": context_snapshot,
            },
        )
        return log_id
