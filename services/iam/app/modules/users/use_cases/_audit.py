from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLog, AuditLogRepository
from sqlalchemy.ext.asyncio import AsyncSession


async def record_user_audit_event(
    session: AsyncSession,
    audit_log: AuditLogRepository,
    event_type: str,
    user_id: uuid.UUID | None,
    context: dict,
) -> None:
    audit_log.add(
        AuditLog(
            id=uuid.uuid4(),
            user_id=user_id,
            event_type=event_type,
            context=context,
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
