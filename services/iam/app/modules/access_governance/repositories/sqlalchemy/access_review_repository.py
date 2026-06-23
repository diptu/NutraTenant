from __future__ import annotations

from app.infrastructure.database.base_repository import BaseRepository
from app.modules.access_governance.models import AccessReview


class AccessReviewRepository(BaseRepository[AccessReview]):
    """Persistence access for :class:`AccessReview`."""

    model = AccessReview
