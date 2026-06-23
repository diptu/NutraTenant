"""Repository contracts for :class:`~app.modules.groups.models.Group` and
:class:`~app.modules.groups.models.GroupMembership`, satisfied structurally
by :mod:`app.modules.groups.repositories.sqlalchemy.group_repository`."""

from __future__ import annotations

import uuid
from typing import Protocol

from app.modules.groups.models import Group, GroupMembership


class GroupRepository(Protocol):
    async def get_by_id(self, entity_id: uuid.UUID) -> Group | None: ...

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[Group]: ...

    def add(self, instance: Group) -> None: ...

    async def delete(self, instance: Group) -> None: ...

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
    ) -> tuple[list[Group], int]: ...

    async def count_members(self, group_id: uuid.UUID) -> int: ...

    async def list_ancestor_ids(self, group_id: uuid.UUID) -> set[uuid.UUID]: ...


class GroupMembershipRepository(Protocol):
    async def get_by_id(self, entity_id: uuid.UUID) -> GroupMembership | None: ...

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[GroupMembership]: ...

    def add(self, instance: GroupMembership) -> None: ...

    async def delete(self, instance: GroupMembership) -> None: ...

    async def get_by_group_and_user(
        self, group_id: uuid.UUID, user_id: uuid.UUID
    ) -> GroupMembership | None: ...

    async def search(
        self,
        *,
        group_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[GroupMembership], int]: ...
