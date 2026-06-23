"""Policy.type/status (migration 0023) — backing the Policies API
(policies_api_spec). ``PolicyEffect`` is deliberately uppercase to match
the spec's wire contract; internally the column/engine still store/compare
lowercase "allow"/"deny" (see app.modules.policies.service._VALID_EFFECTS) —
translated at the route layer, same split as PermissionRiskLevel vs. how
the engine compares it."""

from __future__ import annotations

from typing import Literal

PolicyType = Literal["ABAC", "RBAC"]
PolicyStatus = Literal["DRAFT", "ACTIVE", "PUBLISHED", "INACTIVE"]
PolicyEffect = Literal["ALLOW", "DENY"]
