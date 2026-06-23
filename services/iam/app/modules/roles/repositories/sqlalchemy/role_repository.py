"""Role repository, plus the global role-assignment repository (user_roles)."""

from __future__ import annotations

import uuid

from app.infrastructure.database.associations import (
    RolePermission,
    UserOrganizationRole,
)
from app.infrastructure.database.base_repository import BaseRepository
from app.modules.roles.models import Role, UserRole
from app.modules.users.models import User
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload


class RoleRepository(BaseRepository[Role]):
    """Persistence access for :class:`Role`."""

    model = Role

    async def get_by_code(self, code: str) -> Role | None:
        """Global (organization_id IS NULL) role lookup."""
        stmt = select(Role).where(Role.code == code, Role.organization_id.is_(None))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_code_in_org(self, organization_id: uuid.UUID, code: str) -> Role | None:
        """Org-scoped lookup — role codes are only unique *within* an organization
        (migration 0002's partial unique indexes), never globally."""
        stmt = select(Role).where(Role.organization_id == organization_id, Role.code == code)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name_in_org(self, organization_id: uuid.UUID, name: str) -> Role | None:
        """Fallback for callers that only have a role's *display* name (e.g.
        an admin-facing form posting "Member"/"Admin"), not its `code`. Not
        guaranteed unique by any DB constraint — `name` has no uniqueness
        index, so this returns whichever match comes back first."""
        stmt = select(Role).where(Role.organization_id == organization_id, Role.name == name)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def list_all_global(self) -> list[Role]:
        """Every global (organization_id IS NULL) role — the coarse-grained
        platform RBAC catalog (Admin/Member/Guest, ...)."""
        stmt = select(Role).where(Role.organization_id.is_(None))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def search_catalog(
        self,
        *,
        organization_id: uuid.UUID | None,
        search: str | None = None,
        is_system: bool | None = None,
        is_active: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Role], int]:
        """Filtered, paginated role listing scoped to one tenant
        (``organization_id`` given) or the global catalog (``None``) —
        backs ``GET /api/v1/roles``."""
        filters = [Role.organization_id == organization_id]
        if search:
            filters.append(Role.name.ilike(f"%{search}%"))
        if is_system is not None:
            filters.append(Role.is_system.is_(is_system))
        if is_active is not None:
            filters.append(Role.is_active.is_(is_active))

        count_stmt = select(func.count()).select_from(Role).where(*filters)
        total = (await self._session.execute(count_stmt)).scalar_one()

        stmt = select(Role).where(*filters).order_by(Role.name).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total

    async def count_permissions(self, role_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(RolePermission).where(RolePermission.role_id == role_id)
        return (await self._session.execute(stmt)).scalar_one()

    async def count_users(self, role: Role) -> int:
        """Org-scoped roles count organization_members rows; global roles
        count user_roles rows — two different tables back the two role kinds."""
        if role.organization_id is not None:
            stmt = (
                select(func.count())
                .select_from(UserOrganizationRole)
                .where(UserOrganizationRole.role_id == role.id)
            )
        else:
            stmt = select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id)
        return (await self._session.execute(stmt)).scalar_one()

    async def list_users(self, role: Role) -> list[User]:
        if role.organization_id is not None:
            stmt = (
                select(User)
                .join(UserOrganizationRole, UserOrganizationRole.user_id == User.id)
                .where(UserOrganizationRole.role_id == role.id)
            )
        else:
            stmt = select(User).join(UserRole, UserRole.user_id == User.id).where(UserRole.role_id == role.id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def is_in_use(self, role_id: uuid.UUID) -> bool:
        """True if any organization membership or global role assignment still
        references this role — checked at the application level since SQLite
        (tests) doesn't enforce the FK ``ondelete=RESTRICT`` that protects this
        in Postgres."""
        org_stmt = select(UserOrganizationRole.id).where(UserOrganizationRole.role_id == role_id)
        if (await self._session.execute(org_stmt)).first() is not None:
            return True

        global_stmt = select(UserRole.id).where(UserRole.role_id == role_id)
        return (await self._session.execute(global_stmt)).first() is not None

    async def get_with_permissions(self, role_id: uuid.UUID) -> Role | None:
        stmt = (
            select(Role)
            .where(Role.id == role_id)
            .options(selectinload(Role.role_permissions).selectinload(RolePermission.permission))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


class UserRoleRepository(BaseRepository[UserRole]):
    """Persistence access for :class:`UserRole`."""

    model = UserRole

    async def get(self, user_id: uuid.UUID, role_id: uuid.UUID) -> UserRole | None:
        stmt = select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def has_role(self, user_id: uuid.UUID, role_id: uuid.UUID) -> bool:
        return await self.get(user_id, role_id) is not None

    async def list_for_user(self, user_id: uuid.UUID) -> list[UserRole]:
        stmt = select(UserRole).where(UserRole.user_id == user_id).options(selectinload(UserRole.role))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
