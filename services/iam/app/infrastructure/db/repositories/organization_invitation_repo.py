"""Organization invitation repository."""

from __future__ import annotations

import uuid

from app.infrastructure.db.models.organization_invitation import (
    OrganizationInvitation,
)
from app.infrastructure.db.repositories.base_repository import BaseRepository
from sqlalchemy import select


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
