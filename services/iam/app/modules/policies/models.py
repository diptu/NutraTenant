"""ABAC policy model — maps onto the ``policies`` table (migration 0001,
enriched by migration 0023 for the Policies API, policies_api_spec).

``effect`` is the string ``"allow"`` or ``"deny"`` (enforced at the Pydantic
schema layer, not a DB constraint — matching what migration 0001 actually
created; the API's wire format is the uppercase ``"ALLOW"``/``"DENY"`` from
the spec, translated at the route layer so the engine's deny-overrides
comparisons below don't change). ``conditions`` is the JSON boolean tree
evaluated by app/modules/policies/policy_conditions.py; ``None`` means "matches
unconditionally" whenever ``resource_types``/``actions`` match.

``resource_types``/``actions`` are lists (migration 0023 replaced the
original singular ``resource``/``action`` columns) — a policy now matches
if the candidate resource type is *any* of ``resource_types`` (or that list
contains the ``*`` wildcard), same for actions. ``organization_id`` is the
new optional tenant scope: ``None`` means a global policy (matches every
tenant), set means a policy specific to one organization — same NULL =
global convention as Role/Permission.

Plus the policy evaluation trace table (migration 0006) — one row per PDP
decision: append-only, captures the exact subject/resource/context state at
evaluation time plus a per-policy breakdown, so a denied (or allowed)
decision can be explained after the fact for compliance review. Distinct
from the generic ``audit_logs`` table — this is structured for querying
("show me every deny for resource X last week"), not a generic event blob.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.infrastructure.database.base import Base, PortableJSONB
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    type: Mapped[str] = mapped_column(String(20), nullable=False, default="ABAC")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    effect: Mapped[str] = mapped_column(String(10), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # NULL = a global/platform policy; set = scoped to one tenant.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    )

    resource_types: Mapped[list] = mapped_column(PortableJSONB, nullable=False, default=list)
    actions: Mapped[list] = mapped_column(PortableJSONB, nullable=False, default=list)
    # {"roles": [...], "groups": [...], "users": [...]} — descriptive today,
    # not yet read by PolicyEngineService (conditions are still the only
    # thing actually evaluated); see the Policies API spec's own example.
    subjects: Mapped[dict] = mapped_column(PortableJSONB, nullable=False, default=dict, server_default="{}")
    conditions: Mapped[dict | None] = mapped_column(PortableJSONB, nullable=True)

    # Free-form descriptive metadata (caller-supplied created_by, tags, ...).
    # Mapped to the `metadata` column under a different Python attribute name
    # since `metadata` is reserved on declarative models — same aliasing as
    # Organization.extra_metadata / Group.extra_metadata.
    extra_metadata: Mapped[dict] = mapped_column(
        "metadata", PortableJSONB, nullable=False, default=dict, server_default="{}"
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # No FK in the DB (migration 0001 left it a bare column), same as Resource.created_by.
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


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
