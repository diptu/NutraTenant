"""User repository, including the eager-loaded permission-resolution query."""

from __future__ import annotations

import uuid

from app.infrastructure.database.associations import (
    RolePermission,
    UserOrganizationRole,
    UserPermissionGrant,
)
from app.infrastructure.database.base_repository import BaseRepository
from app.modules.roles.models import Role
from app.modules.users.models import User
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload


class UserRepository(BaseRepository[User]):
    """Persistence access for :class:`User`."""

    model = User

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_google_subject(self, subject: str) -> User | None:
        stmt = select(User).where(User.google_subject == subject)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def search(self, query: str, *, limit: int = 50) -> list[User]:
        pattern = f"%{query.lower()}%"
        stmt = select(User).where(or_(User.email.ilike(pattern), User.full_name.ilike(pattern))).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_organization(
        self,
        organization_id: uuid.UUID,
        query: str | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[User]:
        """Users who are members of `organization_id` — the tenant-scoped
        counterpart to `search`, for an org admin/owner listing only their
        own tenant's users rather than every user platform-wide."""
        stmt = (
            select(User)
            .join(UserOrganizationRole, UserOrganizationRole.user_id == User.id)
            .where(UserOrganizationRole.organization_id == organization_id)
        )
        if query:
            pattern = f"%{query.lower()}%"
            stmt = stmt.where(or_(User.email.ilike(pattern), User.full_name.ilike(pattern)))
        stmt = stmt.limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_with_org_roles(self, user_id: uuid.UUID) -> User | None:
        """Load a user plus its full role→permission chain in one round trip.

        This single query is what lets authorization checks avoid N+1 —
        ``org_roles``/``role``/``role_permissions``/``permission`` are all
        declared ``lazy="raise"`` on the models, so any code path that skips
        this eager-load chain fails loudly instead of issuing per-row queries.
        """
        stmt = (
            select(User)
            .where(User.id == user_id)
            .options(
                selectinload(User.org_roles)
                .selectinload(UserOrganizationRole.role)
                .selectinload(Role.role_permissions)
                .selectinload(RolePermission.permission)
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


class UserPermissionGrantRepository(BaseRepository[UserPermissionGrant]):
    """Persistence access for :class:`UserPermissionGrant` — direct, org-scoped
    user permission grants (table: ``user_permissions``)."""

    model = UserPermissionGrant

    async def get_link(
        self, user_id: uuid.UUID, organization_id: uuid.UUID, permission_id: uuid.UUID
    ) -> UserPermissionGrant | None:
        stmt = select(UserPermissionGrant).where(
            UserPermissionGrant.user_id == user_id,
            UserPermissionGrant.organization_id == organization_id,
            UserPermissionGrant.permission_id == permission_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_user_in_organization(
        self, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> list[UserPermissionGrant]:
        stmt = (
            select(UserPermissionGrant)
            .where(
                UserPermissionGrant.user_id == user_id,
                UserPermissionGrant.organization_id == organization_id,
            )
            .options(selectinload(UserPermissionGrant.permission))
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    def add_link(self, link: UserPermissionGrant) -> None:
        self._session.add(link)

    async def remove_link(self, link: UserPermissionGrant) -> None:
        await self._session.delete(link)
