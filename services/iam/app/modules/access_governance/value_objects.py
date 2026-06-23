"""AccessRequest.status/AccessApproval.decision (migration 0025) — backing
the access-governance workflow (User and Access APIs Specification).
Approving/rejecting only updates these tracked records; it never calls
into RoleService/PermissionService to actually mutate a user's grants —
see app.modules.access_governance.service."""

from __future__ import annotations

from typing import Literal

AccessRequestStatus = Literal["PENDING_APPROVAL", "APPROVED", "REJECTED"]
AccessApprovalDecision = Literal["APPROVED", "REJECTED"]
