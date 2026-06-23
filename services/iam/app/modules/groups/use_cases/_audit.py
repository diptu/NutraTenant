from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLog, AuditLogRepository
from app.modules.groups.models import Group, GroupMembership
from sqlalchemy.ext.asyncio import AsyncSession


async def record_group_audit_event(
    session: AsyncSession,
    audit_log: AuditLogRepository,
    event_type: str,
    actor_id: uuid.UUID | None,
    entity: Group | GroupMembership | None,
    extra: dict,
) -> None:
    context = dict(extra)
    if isinstance(entity, Group):
        context["group_id"] = str(entity.id)
    elif isinstance(entity, GroupMembership):
        context["group_membership_id"] = str(entity.id)
        context["group_id"] = str(entity.group_id)
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
