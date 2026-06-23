from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLog, AuditLogRepository
from app.modules.policies.models import Policy
from sqlalchemy.ext.asyncio import AsyncSession


async def record_policy_audit_event(
    session: AsyncSession,
    audit_log: AuditLogRepository,
    event_type: str,
    actor_id: uuid.UUID,
    policy: Policy,
    extra: dict,
) -> None:
    audit_log.add(
        AuditLog(
            id=uuid.uuid4(),
            user_id=actor_id,
            event_type=event_type,
            context={
                "policy_id": str(policy.id),
                "policy_name": policy.name,
                **extra,
            },
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
