"""A small, deliberately non-Turing-complete boolean condition DSL for ABAC policies.

Stored as JSON in ``policies.conditions`` (see app/modules/policies/models.py).
No ``eval()``, no arbitrary code execution — every node is one of:

- ``{"all": [<condition>, ...]}``  — AND
- ``{"any": [<condition>, ...]}``  — OR
- ``{"not": <condition>}``         — NOT
- ``{"op": "eq", "left": ..., "right": ...}`` — a leaf comparison

``left``/``right`` are either literals or ``{"var": "dotted.path"}``, resolved
against the evaluation context built by the PDP (``subject``, ``resource``,
``action``, ``context`` namespaces — see app/modules/policies/service.py).
A path that doesn't resolve evaluates to ``None`` rather than raising, so a
policy referencing an attribute a particular subject/resource doesn't have
simply doesn't match instead of blowing up evaluation for every other policy.
"""

from __future__ import annotations

import re
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


def _describe_operand(operand: Any) -> str:
    if isinstance(operand, dict) and set(operand) == {"var"}:
        return str(operand["var"]).rsplit(".", 1)[-1]
    return repr(operand)


def trace_condition(node: Any, context: dict[str, Any]) -> list[str]:
    """Best-effort, human-readable per-leaf trace of a conditions tree —
    backs ``POST /policies/{id}/simulate``'s ``matched_rules``. Purely
    diagnostic output: unlike :func:`evaluate_condition`, a malformed node
    here just contributes no trace line rather than raising."""
    traces: list[str] = []
    _trace_into(node, context, traces)
    return traces


def _trace_into(node: Any, context: dict[str, Any], traces: list[str]) -> None:
    if not isinstance(node, dict) or not node:
        return
    if isinstance(node.get("all"), list):
        for child in node["all"]:
            _trace_into(child, context, traces)
        return
    if isinstance(node.get("any"), list):
        for child in node["any"]:
            _trace_into(child, context, traces)
        return
    if "not" in node:
        _trace_into(node["not"], context, traces)
        return
    if "op" in node and "left" in node and "right" in node:
        op = node["op"]
        if op not in _OPS:
            return
        left = _resolve(node["left"], context)
        right = _resolve(node["right"], context)
        try:
            matched = bool(_OPS[op](left, right))
        except TypeError:
            matched = False
        label = _describe_operand(node["left"])
        traces.append(f"{label} {op} {'matched' if matched else 'not matched'}")


_INTERPOLATION_RE = re.compile(r"^\$\{(.+)\}$")
# The Policies API spec (policies_api_spec) writes leaf conditions as
# {"attribute": "user.department", "operator": "eq", "value": "Finance"},
# with a "user" namespace and "${other.path}" string interpolation for
# referencing another attribute as the comparison value — instead of this
# module's native {"op": "eq", "left": {"var": "subject.department"},
# "right": ...} shape (namespaced "subject", and a {"var": ...} object
# rather than string interpolation). Both shapes share the same "all"/
# "any"/"not" combinators and operator names, so normalize_condition
# translates spec-shaped leaves into the native shape at write time —
# evaluate_condition/validate_condition_schema only ever see the native
# shape; nothing about the hardened evaluator itself changes.
_NAMESPACE_ALIASES = {"user": "subject"}


def _map_namespace(path: str) -> str:
    head, _, rest = path.partition(".")
    mapped = _NAMESPACE_ALIASES.get(head, head)
    return f"{mapped}.{rest}" if rest else mapped


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        match = _INTERPOLATION_RE.match(value)
        if match:
            return {"var": _map_namespace(match.group(1))}
    return value


def normalize_condition(node: Any) -> Any:
    """Translates a possibly spec-shaped (``attribute``/``operator``/``value``)
    condition tree into this module's native (``op``/``left``/``right``)
    shape. A tree already in the native shape passes through unchanged.
    Structural validity isn't checked here — call :func:`validate_condition_schema`
    on the result afterwards."""
    if node is None or not isinstance(node, dict):
        return node

    if isinstance(node.get("all"), list):
        return {"all": [normalize_condition(child) for child in node["all"]]}
    if isinstance(node.get("any"), list):
        return {"any": [normalize_condition(child) for child in node["any"]]}
    if "not" in node:
        return {"not": normalize_condition(node["not"])}

    if "attribute" in node and "operator" in node:
        return {
            "op": node["operator"],
            "left": {"var": _map_namespace(str(node["attribute"]))},
            "right": _normalize_value(node.get("value")),
        }

    if "op" in node:
        return {
            "op": node["op"],
            "left": _normalize_value(node.get("left")) if "left" in node else node.get("left"),
            "right": _normalize_value(node.get("right")) if "right" in node else node.get("right"),
        }

    return node


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
