from __future__ import annotations

import uuid

from app.modules.policies.policy_conditions import trace_condition
from app.modules.policies.schemas.dto.simulation_result_dto import SimulationResult
from app.modules.policies.schemas.queries.simulate_policy_query import SimulatePolicyQuery
from app.modules.policies.use_cases._matching import match_one


class SimulatePolicyUseCase:
    """Dry-runs a single named policy against a synthetic subject/
    resource/context — backs ``POST /policies/{policy_id}/simulate``.

    Deliberately not persisted to ``PolicyEvaluationLog``: that table's
    ``user_id`` is a real FK to ``users.id``, and a simulated subject is
    an arbitrary synthetic payload (see ``PolicySimulateRequest``), not
    necessarily a real registered user.
    """

    def execute(self, query: SimulatePolicyQuery) -> SimulationResult:
        eval_context = {
            "subject": query.subject,
            "resource": query.resource,
            "action": query.action,
            "context": query.context or {},
        }
        match = match_one(query.policy, eval_context)
        decision = query.policy.effect if match.matched else "deny"
        matched_rules = (
            trace_condition(query.policy.conditions, eval_context) if query.policy.conditions else []
        )
        return SimulationResult(
            decision=decision,
            matched=match.matched,
            matched_rules=matched_rules,
            evaluation_id=uuid.uuid4(),
        )
