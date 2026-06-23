"""Permission catalog repository, including role/usage lookups for the
Permission Management API."""

from __future__ import annotations

import uuid

from app.infrastructure.database.associations import (
    RolePermission,
    UserOrganizationRole,
    UserPermissionGrant,
)
from app.infrastructure.database.base_repository import BaseRepository
from app.modules.permissions.models import Permission
from app.modules.roles.models import Role, UserRole
from sqlalchemy import func, or_, select


class PermissionRepository(BaseRepository[Permission]):
    """Persistence access for :class:`Permission` and its role associations."""

    model = Permission

    async def get_by_code(self, code: str) -> Permission | None:
        stmt = select(Permission).where(Permission.code == code)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

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
    ) -> tuple[list[Permission], int]:
        """Filtered, paginated catalog listing — returns ``(page, total)``."""
        filters = []
        if resource is not None:
            filters.append(Permission.resource == resource)
        if action is not None:
            filters.append(Permission.action == action)
        if category is not None:
            filters.append(Permission.category == category)
        if status is not None:
            filters.append(Permission.status == status)
        if q:
            like = f"%{q}%"
            filters.append(or_(Permission.name.ilike(like), Permission.description.ilike(like)))

        count_stmt = select(func.count()).select_from(Permission).where(*filters)
        total = (await self._session.execute(count_stmt)).scalar_one()

        stmt = select(Permission).where(*filters).order_by(Permission.name).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total

    async def search(self, q: str, *, limit: int = 50) -> list[Permission]:
        like = f"%{q}%"
        stmt = (
            select(Permission)
            .where(or_(Permission.name.ilike(like), Permission.description.ilike(like)))
            .order_by(Permission.name)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_role_permission(
        self, role_id: uuid.UUID, permission_id: uuid.UUID
    ) -> RolePermission | None:
        stmt = select(RolePermission).where(
            RolePermission.role_id == role_id,
            RolePermission.permission_id == permission_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    def add_role_permission(self, link: RolePermission) -> None:
        self._session.add(link)

    async def remove_role_permission(self, link: RolePermission) -> None:
        await self._session.delete(link)

    async def list_roles_for_permission(self, permission_id: uuid.UUID) -> list[Role]:
        stmt = (
            select(Role)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .where(RolePermission.permission_id == permission_id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_roles_for_permission(self, permission_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(RolePermission)
            .where(RolePermission.permission_id == permission_id)
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def list_direct_grant_user_ids(self, permission_id: uuid.UUID) -> set[uuid.UUID]:
        stmt = select(UserPermissionGrant.user_id).where(UserPermissionGrant.permission_id == permission_id)
        result = await self._session.execute(stmt)
        return set(result.scalars().all())

    async def list_role_grantee_user_ids(self, permission_id: uuid.UUID) -> set[uuid.UUID]:
        """Every user who holds this permission *via a role* — org-scoped
        membership roles (organization_members) and global roles (user_roles)
        are two separate tables, so this is a union of two queries rather
        than one join."""
        org_stmt = (
            select(UserOrganizationRole.user_id)
            .join(RolePermission, RolePermission.role_id == UserOrganizationRole.role_id)
            .where(RolePermission.permission_id == permission_id)
        )
        global_stmt = (
            select(UserRole.user_id)
            .join(RolePermission, RolePermission.role_id == UserRole.role_id)
            .where(RolePermission.permission_id == permission_id)
        )
        org_ids = set((await self._session.execute(org_stmt)).scalars().all())
        global_ids = set((await self._session.execute(global_stmt)).scalars().all())
        return org_ids | global_ids
