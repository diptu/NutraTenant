"""Permission.risk_level / Permission.status (migration 0020) — backing the
Permission Management API's PATCH .../enable|disable and the risk_level
field on create/update."""

from __future__ import annotations

from typing import Literal

PermissionRiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
PermissionStatus = Literal["ACTIVE", "DISABLED"]
