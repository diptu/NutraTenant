from __future__ import annotations

from datetime import UTC, datetime

from app.modules.organizations.exceptions import InvitationNotFoundError
from app.modules.organizations.repositories.interfaces.organization_repository import (
    OrganizationInvitationRepository,
)
from app.modules.organizations.schemas.commands.revoke_invitation_command import (
    RevokeInvitationCommand,
)
from sqlalchemy.ext.asyncio import AsyncSession


class RevokeInvitationUseCase:
    def __init__(self, session: AsyncSession, invitations: OrganizationInvitationRepository) -> None:
        self._session = session
        self._invitations = invitations

    async def execute(self, command: RevokeInvitationCommand) -> None:
        invitation = await self._invitations.get_by_id(command.invitation_id)
        if (
            invitation is None
            or invitation.organization_id != command.organization_id
            or invitation.accepted_at is not None
            or invitation.revoked_at is not None
        ):
            raise InvitationNotFoundError("No pending invitation with this id")
        invitation.revoked_at = datetime.now(UTC)
        await self._session.commit()
