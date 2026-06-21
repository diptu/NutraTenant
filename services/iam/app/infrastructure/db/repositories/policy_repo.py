"""ABAC policy repository."""

from __future__ import annotations

from app.infrastructure.db.models.policy import Policy
from app.infrastructure.db.repositories.base_repository import BaseRepository
from sqlalchemy import or_, select

_WILDCARD = "*"


class PolicyRepository(BaseRepository[Policy]):
    """Persistence access for :class:`Policy`."""

    model = Policy

    async def get_by_name(self, name: str) -> Policy | None:
        stmt = select(Policy).where(Policy.name == name)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_matching(self, resource: str, action: str) -> list[Policy]:
        """Active policies whose resource/action match exactly or via the
        ``*`` wildcard — the candidate set the PDP evaluates conditions against."""
        stmt = select(Policy).where(
            Policy.is_active.is_(True),
            or_(Policy.resource == resource, Policy.resource == _WILDCARD),
            or_(Policy.action == action, Policy.action == _WILDCARD),
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
