from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLog, AuditLogRepository
from app.modules.permissions.models import Permission
from sqlalchemy.ext.asyncio import AsyncSession


async def record_permission_audit_event(
    session: AsyncSession,
    audit_log: AuditLogRepository,
    event_type: str,
    actor_id: uuid.UUID | None,
    permission: Permission | None,
    extra: dict,
) -> None:
    context = dict(extra)
    if permission is not None:
        context["permission_id"] = str(permission.id)
        context["code"] = permission.code
    audit_log.add(
        AuditLog(
            id=uuid.uuid4(),
            user_id=actor_id,
            event_type=event_type,
            context=context,
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
