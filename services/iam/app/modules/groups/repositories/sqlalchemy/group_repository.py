"""Group catalog repository (parent-hierarchy and member-count lookups),
plus the group membership repository."""

from __future__ import annotations

import uuid

from app.infrastructure.database.base_repository import BaseRepository
from app.modules.groups.models import Group, GroupMembership
from sqlalchemy import func, select


class GroupRepository(BaseRepository[Group]):
    """Persistence access for :class:`Group`."""

    model = Group

    async def search_catalog(
        self,
        *,
        organization_id: uuid.UUID,
        type: str | None = None,
        status: str | None = None,
        parent_group_id: uuid.UUID | None = None,
        search: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Group], int]:
        """Filtered, paginated group listing scoped to one tenant — backs
        ``GET /api/v1/groups``."""
        filters = [Group.organization_id == organization_id]
        if type is not None:
            filters.append(Group.type == type)
        if status is not None:
            filters.append(Group.status == status)
        if parent_group_id is not None:
            filters.append(Group.parent_group_id == parent_group_id)
        if search:
            filters.append(Group.name.ilike(f"%{search}%"))

        count_stmt = select(func.count()).select_from(Group).where(*filters)
        total = (await self._session.execute(count_stmt)).scalar_one()

        stmt = select(Group).where(*filters).order_by(Group.name).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total

    async def count_members(self, group_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(GroupMembership)
            .where(GroupMembership.group_id == group_id, GroupMembership.status == "ACTIVE")
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def list_ancestor_ids(self, group_id: uuid.UUID) -> set[uuid.UUID]:
        """Walks ``parent_group_id`` upward from ``group_id`` — used to reject
        a parent assignment that would close a cycle. Bounded by the number
        of groups in existence, so a corrupt cycle already in the data can't
        loop forever."""
        ancestors: set[uuid.UUID] = set()
        current_id: uuid.UUID | None = group_id
        while current_id is not None and current_id not in ancestors:
            ancestors.add(current_id)
            current = await self.get_by_id(current_id)
            current_id = current.parent_group_id if current is not None else None
        return ancestors


class GroupMembershipRepository(BaseRepository[GroupMembership]):
    """Persistence access for :class:`GroupMembership`."""

    model = GroupMembership

    async def get_by_group_and_user(self, group_id: uuid.UUID, user_id: uuid.UUID) -> GroupMembership | None:
        stmt = select(GroupMembership).where(
            GroupMembership.group_id == group_id, GroupMembership.user_id == user_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def search(
        self,
        *,
        group_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[GroupMembership], int]:
        """Filtered, paginated membership listing — backs
        ``GET /api/v1/group-memberships``."""
        filters = []
        if group_id is not None:
            filters.append(GroupMembership.group_id == group_id)
        if user_id is not None:
            filters.append(GroupMembership.user_id == user_id)
        if status is not None:
            filters.append(GroupMembership.status == status)

        count_stmt = select(func.count()).select_from(GroupMembership).where(*filters)
        total = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            select(GroupMembership)
            .where(*filters)
            .order_by(GroupMembership.created_at)
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total
