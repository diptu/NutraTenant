"""Repository contract for :class:`~app.modules.permissions.models.Permission`,
satisfied structurally by
:class:`~app.modules.permissions.repositories.sqlalchemy.permission_repository.PermissionRepository`."""

from __future__ import annotations

import uuid
from typing import Protocol

from app.infrastructure.database.associations import RolePermission
from app.modules.permissions.models import Permission
from app.modules.roles.models import Role


class PermissionRepository(Protocol):
    async def get_by_id(self, entity_id: uuid.UUID) -> Permission | None: ...

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[Permission]: ...

    def add(self, instance: Permission) -> None: ...

    async def delete(self, instance: Permission) -> None: ...

    async def get_by_code(self, code: str) -> Permission | None: ...

    async def search_catalog(
        self,
        *,
        resource: str | None = None,
        action: str | None = None,
        category: str | None = None,
        status: str | None = None,
        q: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Permission], int]: ...

    async def search(self, q: str, *, limit: int = 50) -> list[Permission]: ...

    async def get_role_permission(
        self, role_id: uuid.UUID, permission_id: uuid.UUID
    ) -> RolePermission | None: ...

    def add_role_permission(self, link: RolePermission) -> None: ...

    async def remove_role_permission(self, link: RolePermission) -> None: ...

    async def list_roles_for_permission(self, permission_id: uuid.UUID) -> list[Role]: ...

    async def count_roles_for_permission(self, permission_id: uuid.UUID) -> int: ...

    async def list_direct_grant_user_ids(self, permission_id: uuid.UUID) -> set[uuid.UUID]: ...

    async def list_role_grantee_user_ids(self, permission_id: uuid.UUID) -> set[uuid.UUID]: ...
