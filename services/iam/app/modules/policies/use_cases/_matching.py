from __future__ import annotations

from typing import Any

from app.modules.policies.models import Policy
from app.modules.policies.policy_conditions import ConditionError, evaluate_condition
from app.modules.policies.schemas.dto.pdp_result_dto import PolicyMatchResult


def match_one(policy: Policy, eval_context: dict[str, Any]) -> PolicyMatchResult:
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
