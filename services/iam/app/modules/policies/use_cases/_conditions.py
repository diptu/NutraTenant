from __future__ import annotations

from app.modules.policies.exceptions import InvalidPolicyConditionsError
from app.modules.policies.policy_conditions import (
    ConditionError,
    normalize_condition,
    validate_condition_schema,
)

VALID_EFFECTS = ("allow", "deny")


def validate_effect(effect: str) -> None:
    if effect not in VALID_EFFECTS:
        raise InvalidPolicyConditionsError(f"effect must be one of {VALID_EFFECTS}, got '{effect}'")


def normalize_and_validate_conditions(conditions: dict | None) -> dict | None:
    """Translates the spec's ``attribute``/``operator``/``value`` leaf
    shape (and ``${path}`` interpolation) into this module's native
    ``op``/``left``/``right`` shape before validating — see
    app.modules.policies.policy_conditions.normalize_condition. A tree
    already in the native shape passes through unchanged."""
    normalized = normalize_condition(conditions)
    try:
        validate_condition_schema(normalized)
    except ConditionError as exc:
        raise InvalidPolicyConditionsError(str(exc)) from exc
    return normalized
