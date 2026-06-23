from __future__ import annotations

from app.infrastructure.database.base_repository import BaseRepository
from app.modules.access_governance.models import AccessRequest


class AccessRequestRepository(BaseRepository[AccessRequest]):
    """Persistence access for :class:`AccessRequest`."""

    model = AccessRequest
