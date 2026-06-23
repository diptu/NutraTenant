"""Access governance models — backs /api/v1/access-requests, /access-reviews,
/access-approvals (migration 0025, User and Access APIs Specification).

AccessRequest: a tracked record of someone asking for elevated roles/
permissions; ``status`` only ever changes via an AccessApproval decision
(see app.modules.access_governance.service) — it never causes the
requested grant to actually happen.

AccessReview: a tracked record that a periodic (or ad-hoc) access review
was opened for a tenant — purely a governance record today, no automated
review logic runs against it.

AccessApproval: recording a decision against an AccessRequest is the
*only* effect this has — see app.modules.access_governance.service for why
it deliberately never calls into RoleService/PermissionService to apply
the requested grant.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.infrastructure.database.base import Base, PortableJSONB
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class AccessRequest(Base):
    __tablename__ = "access_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    requested_roles: Mapped[list] = mapped_column(PortableJSONB, nullable=False, default=list)
    requested_permissions: Mapped[list] = mapped_column(PortableJSONB, nullable=False, default=list)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING_APPROVAL")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccessReview(Base):
    __tablename__ = "access_reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    review_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    review_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccessApproval(Base):
    __tablename__ = "access_approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    access_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("access_requests.id", ondelete="CASCADE"), nullable=False
    )

    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="COMPLETED")

    processed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
