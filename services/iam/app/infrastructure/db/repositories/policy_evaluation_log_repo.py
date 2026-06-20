"""Policy evaluation trace repository — append-only, like AuditLogRepository."""

from __future__ import annotations

from app.infrastructure.db.models.policy_evaluation_log import PolicyEvaluationLog
from app.infrastructure.db.repositories.base_repository import BaseRepository


class PolicyEvaluationLogRepository(BaseRepository[PolicyEvaluationLog]):
    """Persistence access for :class:`PolicyEvaluationLog`."""

    model = PolicyEvaluationLog
