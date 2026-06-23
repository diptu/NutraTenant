"""Repository contracts for :class:`~app.modules.users.models.User` and
:class:`~app.infrastructure.database.associations.UserPermissionGrant`,
satisfied structurally by
:mod:`app.modules.users.repositories.sqlalchemy.user_repository`."""

from __future__ import annotations

import uuid
from typing import Protocol

from app.infrastructure.database.associations import UserPermissionGrant
from app.modules.users.models import User


class UserRepository(Protocol):
    async def get_by_id(self, entity_id: uuid.UUID) -> User | None: ...

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[User]: ...

    def add(self, instance: User) -> None: ...

    async def delete(self, instance: User) -> None: ...

    async def get_by_email(self, email: str) -> User | None: ...

    async def get_by_google_subject(self, subject: str) -> User | None: ...

    async def get_by_username(self, username: str) -> User | None: ...

    async def search(self, query: str, *, limit: int = 50) -> list[User]: ...

    async def list_for_organization(
        self,
        organization_id: uuid.UUID,
        query: str | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[User]: ...

    async def get_with_org_roles(self, user_id: uuid.UUID) -> User | None: ...


class UserPermissionGrantRepository(Protocol):
    async def get_by_id(self, entity_id: uuid.UUID) -> UserPermissionGrant | None: ...

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[UserPermissionGrant]: ...

    def add(self, instance: UserPermissionGrant) -> None: ...

    async def delete(self, instance: UserPermissionGrant) -> None: ...

    async def get_link(
        self, user_id: uuid.UUID, organization_id: uuid.UUID, permission_id: uuid.UUID
    ) -> UserPermissionGrant | None: ...

    async def list_for_user_in_organization(
        self, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> list[UserPermissionGrant]: ...

    def add_link(self, link: UserPermissionGrant) -> None: ...

    async def remove_link(self, link: UserPermissionGrant) -> None: ...
