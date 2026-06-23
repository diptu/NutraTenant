"""Organization repository, plus the organization-invitation repository."""

from __future__ import annotations

import uuid

from app.infrastructure.database.associations import (
    RolePermission,
    UserOrganizationRole,
)
from app.infrastructure.database.base_repository import BaseRepository
from app.modules.organizations.models import Organization, OrganizationInvitation
from app.modules.roles.models import Role
from sqlalchemy import select
from sqlalchemy.orm import selectinload


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

    async def list_members(self, organization_id: uuid.UUID) -> list[UserOrganizationRole]:
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


class OrganizationInvitationRepository(BaseRepository[OrganizationInvitation]):
    """Persistence access for :class:`OrganizationInvitation`."""

    model = OrganizationInvitation

    async def get_by_token_hash(self, token_hash: str) -> OrganizationInvitation | None:
        stmt = select(OrganizationInvitation).where(OrganizationInvitation.token_hash == token_hash)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pending_for_org_and_email(
        self, organization_id: uuid.UUID, email: str
    ) -> OrganizationInvitation | None:
        stmt = select(OrganizationInvitation).where(
            OrganizationInvitation.organization_id == organization_id,
            OrganizationInvitation.email == email,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_pending_for_org(self, organization_id: uuid.UUID) -> list[OrganizationInvitation]:
        stmt = select(OrganizationInvitation).where(
            OrganizationInvitation.organization_id == organization_id,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
