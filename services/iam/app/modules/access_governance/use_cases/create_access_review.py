from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.access_governance.models import AccessReview
from app.modules.access_governance.repositories.interfaces.access_review_repository import (
    AccessReviewRepository,
)
from app.modules.access_governance.schemas.commands.create_access_review_command import (
    CreateAccessReviewCommand,
)
from app.modules.access_governance.use_cases._audit import record_audit_event
from sqlalchemy.ext.asyncio import AsyncSession


class CreateAccessReviewUseCase:
    def __init__(
        self,
        session: AsyncSession,
        reviews: AccessReviewRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._session = session
        self._reviews = reviews
        self._audit_log = audit_log

    async def execute(self, command: CreateAccessReviewCommand) -> AccessReview:
        now = datetime.now(UTC)
        review = AccessReview(
            id=uuid.uuid4(),
            review_scope=command.review_scope,
            organization_id=command.organization_id,
            review_type=command.review_type,
            status="OPEN",
            created_by=command.created_by,
            created_at=now,
            updated_at=now,
        )
        self._reviews.add(review)
        await self._session.flush()

        await record_audit_event(
            self._session,
            self._audit_log,
            "access.review.opened",
            command.created_by,
            {
                "access_review_id": str(review.id),
                "review_scope": command.review_scope,
                "review_type": command.review_type,
            },
        )
        return review
