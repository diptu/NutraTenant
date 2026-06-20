"""A small, deliberately non-Turing-complete boolean condition DSL for ABAC policies.

Stored as JSON in ``policies.conditions`` (see app/infrastructure/db/models/policy.py).
No ``eval()``, no arbitrary code execution — every node is one of:

- ``{"all": [<condition>, ...]}``  — AND
- ``{"any": [<condition>, ...]}``  — OR
- ``{"not": <condition>}``         — NOT
- ``{"op": "eq", "left": ..., "right": ...}`` — a leaf comparison

``left``/``right`` are either literals or ``{"var": "dotted.path"}``, resolved
against the evaluation context built by the PDP (``subject``, ``resource``,
``action``, ``context`` namespaces — see app/services/policy_engine_service.py).
A path that doesn't resolve evaluates to ``None`` rather than raising, so a
policy referencing an attribute a particular subject/resource doesn't have
simply doesn't match instead of blowing up evaluation for every other policy.
"""

from __future__ import annotations

from typing import Any

_OPS: dict[str, Any] = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
    "contains": lambda a, b: b in a,
}


class ConditionError(ValueError):
    """A condition node is structurally malformed."""


def _resolve(operand: Any, context: dict[str, Any]) -> Any:
    if isinstance(operand, dict) and set(operand) == {"var"}:
        value: Any = context
        for part in str(operand["var"]).split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return None
        return value
    return operand


def evaluate_condition(node: dict[str, Any], context: dict[str, Any]) -> bool:
    if not isinstance(node, dict) or not node:
        raise ConditionError("A condition node must be a non-empty object")

    if "all" in node:
        children = node["all"]
        if not isinstance(children, list) or not children:
            raise ConditionError("'all' must be a non-empty list of conditions")
        return all(evaluate_condition(child, context) for child in children)

    if "any" in node:
        children = node["any"]
        if not isinstance(children, list) or not children:
            raise ConditionError("'any' must be a non-empty list of conditions")
        return any(evaluate_condition(child, context) for child in children)

    if "not" in node:
        return not evaluate_condition(node["not"], context)

    if "op" in node:
        op = node["op"]
        if op not in _OPS:
            raise ConditionError(f"Unknown operator '{op}'")
        if "left" not in node or "right" not in node:
            raise ConditionError("A leaf condition needs both 'left' and 'right'")
        left = _resolve(node["left"], context)
        right = _resolve(node["right"], context)
        try:
            return bool(_OPS[op](left, right))
        except TypeError:
            # Comparing incompatible types (e.g. `gt` on a None) is a
            # non-match, not an evaluation failure.
            return False

    raise ConditionError("A condition node must contain 'all', 'any', 'not', or 'op'")


def validate_condition_schema(node: Any) -> None:
    """Structural validation only, run at policy write-time.

    Evaluates the tree against an empty context — any structural error
    (unknown op, malformed combinator, missing leaf keys) still raises
    ``ConditionError`` since that doesn't depend on context contents; the
    boolean result itself is discarded.
    """
    if node is None:
        return
    if not isinstance(node, dict):
        raise ConditionError("conditions must be a JSON object or null")
    evaluate_condition(node, context={})
