"""ReservedTenantId model — backs the reserved-tenant_id blocklist
(migration 0027). A row here means that ``tenant_id`` (an Organization's
``slug``) can never be claimed by POST /api/v1/organizations — used to keep
system/platform words (``admin``, ``api``, ``www``, ...) out of the
subdomain-per-tenant routing space, and to let a superuser block specific
slugs administratively.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.infrastructure.database.base import Base
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class ReservedTenantId(Base):
    __tablename__ = "reserved_tenant_ids"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
