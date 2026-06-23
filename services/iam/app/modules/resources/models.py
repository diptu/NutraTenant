"""Resource model — maps onto the pre-existing ``resources`` table (migration 0001).

This is the "Resource Classification Schema" from the checklist: a catalog
of protectable resources tagged with free-form metadata (``Confidentiality``,
``OwnerID``, ``Region``, ...) that a future ABAC policy engine evaluates
against. No policy engine exists yet — this model only covers registering
and managing the catalog entries themselves.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.infrastructure.database.base import Base, PortableJSONB
from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Python attr `tags` (what the checklist calls these), DB column `schema`
    # (migration 0001's name) — same aliasing trick as Role.code/Permission.code.
    tags: Mapped[dict | None] = mapped_column("schema", PortableJSONB, nullable=True)

    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # No FK in the DB (migration 0001 left it a bare column) — kept as-is
    # rather than retrofitting a constraint unrelated to this checklist slice.
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
