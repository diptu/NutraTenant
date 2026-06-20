"""Organization repository."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.infrastructure.db.models.associations import (
    RolePermission,
    UserOrganizationRole,
)
from app.infrastructure.db.models.organization import Organization
from app.infrastructure.db.models.role import Role
from app.infrastructure.db.repositories.base_repository import BaseRepository


class OrganizationRepository(BaseRepository[Organization]):
    """Persistence access for :class:`Organization`."""

    model = Organization

    async def get_by_slug(self, slug: str) -> Organization | None:
        stmt = select(Organization).where(Organization.slug == slug)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[Organization]:
        """Organizations ``user_id`` is a member of — never a cross-tenant view."""
        stmt = (
            select(Organization)
            .join(
                UserOrganizationRole,
                UserOrganizationRole.organization_id == Organization.id,
            )
            .where(UserOrganizationRole.user_id == user_id)
            .distinct()
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_membership(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> UserOrganizationRole | None:
        stmt = (
            select(UserOrganizationRole)
            .where(
                UserOrganizationRole.organization_id == organization_id,
                UserOrganizationRole.user_id == user_id,
            )
            .options(
                selectinload(UserOrganizationRole.role)
                .selectinload(Role.role_permissions)
                .selectinload(RolePermission.permission)
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_members(
        self, organization_id: uuid.UUID
    ) -> list[UserOrganizationRole]:
        stmt = (
            select(UserOrganizationRole)
            .where(UserOrganizationRole.organization_id == organization_id)
            .options(
                selectinload(UserOrganizationRole.user),
                selectinload(UserOrganizationRole.role),
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    def add_membership(self, membership: UserOrganizationRole) -> None:
        self._session.add(membership)

    async def remove_membership(self, membership: UserOrganizationRole) -> None:
        await self._session.delete(membership)

    async def count_owners(self, organization_id: uuid.UUID) -> int:
        stmt = (
            select(UserOrganizationRole.id)
            .join(Role, Role.id == UserOrganizationRole.role_id)
            .where(
                UserOrganizationRole.organization_id == organization_id,
                Role.code == "owner",
            )
        )
        return len((await self._session.execute(stmt)).all())
