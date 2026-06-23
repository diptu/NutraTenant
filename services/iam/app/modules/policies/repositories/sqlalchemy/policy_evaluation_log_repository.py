from __future__ import annotations

from app.infrastructure.database.base_repository import BaseRepository
from app.modules.policies.models import PolicyEvaluationLog


class PolicyEvaluationLogRepository(BaseRepository[PolicyEvaluationLog]):
    """Persistence access for :class:`PolicyEvaluationLog`."""

    model = PolicyEvaluationLog
