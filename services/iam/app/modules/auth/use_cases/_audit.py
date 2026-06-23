from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLog, AuditLogRepository
from sqlalchemy.ext.asyncio import AsyncSession


async def record_auth_audit_event(
    session: AsyncSession,
    audit_log: AuditLogRepository,
    event_type: str,
    user_id: uuid.UUID | None,
    context: dict,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    audit_log.add(
        AuditLog(
            id=uuid.uuid4(),
            user_id=user_id,
            event_type=event_type,
            ip_address=ip_address,
            user_agent=user_agent,
            context=context,
            created_at=datetime.now(UTC),
        )
    )
    # Commit, not flush: every audit call here is the last write of either
    # a success path or a "reject this request" path (lockout, reuse
    # detection). On the reject paths the caller raises a DomainError
    # right after this, and the request-scoped session dependency rolls
    # back on any exception — without an explicit commit here, the audit
    # row (and e.g. the failed_login_count bump) would vanish along with
    # the exception instead of surviving it.
    await session.commit()
