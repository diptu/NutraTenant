"""Role repository."""

import uuid

from app.infrastructure.db.models.associations import (
    RolePermission,
    UserOrganizationRole,
)
from app.infrastructure.db.models.role import Role
from app.infrastructure.db.models.user_role import UserRole
from app.infrastructure.db.repositories.base_repository import BaseRepository
from sqlalchemy import select
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
