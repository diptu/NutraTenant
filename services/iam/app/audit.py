"""Audit logging — genuinely cross-domain: every domain's service writes to
this same append-only table, so the model + repository live here rather
than under any one domain.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.infrastructure.database.base import Base, PortableJSONB
from app.infrastructure.database.base_repository import BaseRepository
from sqlalchemy import DateTime, ForeignKey, String, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Python attr renamed from the reserved `metadata` name (DeclarativeBase
    # already owns that attribute for the table's MetaData object).
    context: Mapped[dict] = mapped_column(
        "metadata", PortableJSONB, nullable=False, default=dict, server_default="{}"
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditLogRepository(BaseRepository[AuditLog]):
    """Persistence access for :class:`AuditLog` — append-only, no
    update/delete operations exposed."""

    model = AuditLog

    async def list_by_event_prefix(self, prefix: str, *, limit: int = 200) -> list[AuditLog]:
        """Coarse SQL prefetch by event_type prefix (e.g. "permission.") —
        callers needing to scope further by an id embedded in `context`
        (a JSON column) filter in Python afterward to avoid a cross-dialect
        (SQLite-in-tests vs Postgres) JSON-containment query."""
        stmt = (
            select(AuditLog)
            .where(AuditLog.event_type.like(f"{prefix}%"))
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
