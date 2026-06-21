"""Policy evaluation trace — new table introduced in migration 0006.

One row per PDP decision: append-only, captures the exact subject/resource/
context state at evaluation time plus a per-policy breakdown, so a denied
(or allowed) decision can be explained after the fact for compliance review.
Distinct from the generic ``audit_logs`` table — this is structured for
querying ("show me every deny for resource X last week"), not a generic
event blob.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.infrastructure.db.base import Base
from app.infrastructure.db.types import PortableJSONB
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class PolicyEvaluationLog(Base):
    __tablename__ = "policy_evaluation_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    decision: Mapped[str] = mapped_column(String(10), nullable=False)

    matched_policies: Mapped[list] = mapped_column(PortableJSONB, nullable=False, default=list)
    subject_snapshot: Mapped[dict] = mapped_column(PortableJSONB, nullable=False, default=dict)
    resource_snapshot: Mapped[dict] = mapped_column(PortableJSONB, nullable=False, default=dict)
    context_snapshot: Mapped[dict] = mapped_column(PortableJSONB, nullable=False, default=dict)

    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
