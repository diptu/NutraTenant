"""The Policy Decision Point (PDP) — deterministic ABAC evaluation with
deny-overrides conflict resolution.

Algorithm:
  1. Pull the candidate set: active policies whose resource/action match
     (exactly, or via the ``*`` wildcard) — see PolicyRepository.list_matching.
  2. For each candidate, evaluate its ``conditions`` tree (None = matches
     unconditionally) against {subject, resource, action, context}.
  3. Conflict resolution is deny-overrides: any matched "deny" policy wins
     outright, regardless of how many "allow" policies also matched.
  4. No policy matched at all -> default deny (secure by default, never
     fail open).

Every evaluation is persisted (PolicyEvaluationLog) *and* emitted as a
structured JSON log line — the "why did this fail" trail Section 8 asks for.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.domain.policy_conditions import ConditionError, evaluate_condition
from app.infrastructure.db.models.policy_evaluation_log import PolicyEvaluationLog
from app.infrastructure.db.models.user import User
from app.infrastructure.db.repositories.policy_evaluation_log_repo import (
    PolicyEvaluationLogRepository,
)
from app.infrastructure.db.repositories.policy_repo import PolicyRepository

_logger = get_logger("abac.pdp")


@dataclass(frozen=True, slots=True)
class PolicyMatchResult:
    policy_id: uuid.UUID
    policy_name: str
    effect: str
    matched: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy_id": str(self.policy_id),
            "policy_name": self.policy_name,
            "effect": self.effect,
            "matched": self.matched,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class PDPResult:
    decision: str
    matched_policies: list[PolicyMatchResult] = field(default_factory=list)
    subject_snapshot: dict[str, Any] = field(default_factory=dict)
    resource_snapshot: dict[str, Any] = field(default_factory=dict)
    context_snapshot: dict[str, Any] = field(default_factory=dict)
    log_id: uuid.UUID | None = None

    @property
    def is_allowed(self) -> bool:
        return self.decision == "allow"


class PolicyEngineService:
    def __init__(self, session) -> None:
        self._session = session
        self._policies = PolicyRepository(session)
        self._logs = PolicyEvaluationLogRepository(session)

    async def evaluate(
        self,
        *,
        subject: User,
        resource_type: str,
        action: str,
        resource_id: uuid.UUID | None = None,
        resource_attributes: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> PDPResult:
        candidates = await self._policies.list_matching(resource_type, action)

        subject_snapshot = {
            "id": str(subject.id),
            "email": subject.email,
            "is_superuser": subject.is_superuser,
            "attributes": subject.attributes or {},
        }
        resource_snapshot: dict[str, Any] = {
            "type": resource_type,
            "id": str(resource_id) if resource_id else None,
            **(resource_attributes or {}),
        }
        context_snapshot = context or {}

        eval_context = {
            "subject": subject_snapshot,
            "resource": resource_snapshot,
            "action": action,
            "context": context_snapshot,
        }

        matches = [self._match_one(policy, eval_context) for policy in candidates]

        deny_matched = any(m.matched and m.effect == "deny" for m in matches)
        allow_matched = any(m.matched and m.effect == "allow" for m in matches)
        if deny_matched:
            decision = "deny"
        elif allow_matched:
            decision = "allow"
        else:
            decision = "deny"  # default-deny: no matching policy is not implicit access

        log_id = await self._record(
            subject_id=subject.id,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
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

    def _match_one(self, policy: Any, eval_context: dict[str, Any]) -> PolicyMatchResult:
        if policy.conditions is None:
            return PolicyMatchResult(
                policy_id=policy.id,
                policy_name=policy.name,
                effect=policy.effect,
                matched=True,
                reason="no conditions — matches unconditionally on resource/action",
            )
        try:
            matched = evaluate_condition(policy.conditions, eval_context)
        except ConditionError as exc:
            # A malformed condition never silently grants access.
            return PolicyMatchResult(
                policy_id=policy.id,
                policy_name=policy.name,
                effect=policy.effect,
                matched=False,
                reason=f"conditions malformed, treated as non-match: {exc}",
            )
        return PolicyMatchResult(
            policy_id=policy.id,
            policy_name=policy.name,
            effect=policy.effect,
            matched=matched,
            reason="conditions satisfied" if matched else "conditions not satisfied",
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
