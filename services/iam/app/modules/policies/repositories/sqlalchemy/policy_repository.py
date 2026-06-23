"""ABAC policy repository, plus the policy evaluation trace repository
(append-only, like AuditLogRepository)."""

from __future__ import annotations

import uuid

from app.infrastructure.database.base_repository import BaseRepository
from app.modules.policies.models import Policy
from sqlalchemy import ColumnElement, func, or_, select

_WILDCARD = "*"
_ENFORCED_STATUSES = ("ACTIVE", "PUBLISHED")


class PolicyRepository(BaseRepository[Policy]):
    """Persistence access for :class:`Policy`."""

    model = Policy

    async def get_by_name(self, name: str) -> Policy | None:
        stmt = select(Policy).where(Policy.name == name)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_matching(
        self, resource_type: str, action: str, *, organization_id: uuid.UUID | None = None
    ) -> list[Policy]:
        """The PDP's candidate set: enforced (ACTIVE/PUBLISHED) policies whose
        ``resource_types``/``actions`` contain the given values (or the ``*``
        wildcard), scoped to global policies plus — when given — one tenant.

        ``resource_types``/``actions`` are matched in Python rather than via
        a JSON-containment SQL operator: ``PortableJSONB`` is plain ``JSON``
        (TEXT-backed) on the SQLite test engine, which has no JSONB
        containment support, so this stays portable across both dialects at
        the cost of fetching the (typically small) enforced-policy set per
        evaluation rather than pushing the list-membership filter into SQL.
        """
        filters: list[ColumnElement[bool]] = [Policy.status.in_(_ENFORCED_STATUSES)]
        if organization_id is None:
            filters.append(Policy.organization_id.is_(None))
        else:
            filters.append(or_(Policy.organization_id.is_(None), Policy.organization_id == organization_id))
        stmt = select(Policy).where(*filters)
        result = await self._session.execute(stmt)
        candidates = result.scalars().all()
        return [
            policy
            for policy in candidates
            if _matches(policy.resource_types, resource_type) and _matches(policy.actions, action)
        ]

    async def count_for_resource_action(self, resource_type: str, action: str) -> int:
        """Exact-match count (no wildcard expansion) — used by Permission
        Usage's ``policies_count``, an informational approximation since
        Policy has no FK to Permission, just its own resource_types/actions."""
        stmt = select(Policy)
        result = await self._session.execute(stmt)
        return sum(
            1
            for policy in result.scalars().all()
            if resource_type in policy.resource_types and action in policy.actions
        )

    async def search_catalog(
        self,
        *,
        status: str | None = None,
        type: str | None = None,
        organization_id: uuid.UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Policy], int]:
        """Filtered, paginated catalog listing for the Policies management
        API — unlike :meth:`list_matching`, ``organization_id`` here is a
        plain narrowing filter (None = every tenant's policies, for the
        platform-superuser-only management surface), not a tenant-safety
        boundary."""
        filters = []
        if status is not None:
            filters.append(Policy.status == status)
        if type is not None:
            filters.append(Policy.type == type)
        if organization_id is not None:
            filters.append(Policy.organization_id == organization_id)

        count_stmt = select(func.count()).select_from(Policy).where(*filters)
        total = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            select(Policy)
            .where(*filters)
            .order_by(Policy.priority.desc(), Policy.name)
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total


def _matches(values: list[str], candidate: str) -> bool:
    return candidate in values or _WILDCARD in values
