from __future__ import annotations

from app.infrastructure.database.base_repository import BaseRepository
from app.modules.access_governance.models import AccessApproval


class AccessApprovalRepository(BaseRepository[AccessApproval]):
    """Persistence access for :class:`AccessApproval`."""

    model = AccessApproval
