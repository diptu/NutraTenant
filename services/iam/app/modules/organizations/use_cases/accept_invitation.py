from __future__ import annotations

from datetime import UTC, datetime

from app.infrastructure.database.associations import UserOrganizationRole
from app.modules.auth.exceptions import InvalidTokenError
from app.modules.organizations.repositories.interfaces.organization_repository import (
    OrganizationInvitationRepository,
)
from app.modules.organizations.schemas.commands.accept_invitation_command import (
    AcceptInvitationCommand,
)
from app.modules.organizations.schemas.commands.add_member_command import AddMemberCommand
from app.modules.organizations.use_cases._audit import record_organization_audit_event
from app.modules.organizations.use_cases.add_member import AddMemberUseCase
from app.shared.security.invitation_token import hash_invitation_token
from app.shared.value_objects import Email
from sqlalchemy.ext.asyncio import AsyncSession


def _aware(value: datetime) -> datetime:
    """Postgres' ``DateTime(timezone=True)`` round-trips tz-aware; SQLite (tests
    only) round-trips naive. Normalize before comparing against `datetime.now(UTC)`."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class AcceptInvitationUseCase:
    def __init__(
        self,
        session: AsyncSession,
        invitations: OrganizationInvitationRepository,
        add_member_use_case: AddMemberUseCase,
        audit_log,
    ) -> None:
        self._session = session
        self._invitations = invitations
        self._add_member_use_case = add_member_use_case
        self._audit_log = audit_log

    async def execute(self, command: AcceptInvitationCommand) -> tuple[UserOrganizationRole, str]:
        invitation = await self._invitations.get_by_token_hash(hash_invitation_token(command.raw_token))

        if (
            invitation is None
            or invitation.accepted_at is not None
            or invitation.revoked_at is not None
            or _aware(invitation.expires_at) < datetime.now(UTC)
            or invitation.email != Email(command.accepting_email).value
        ):
            # Same message for "no such token", "already used", "revoked",
            # "expired", and "wrong account" — don't help an attacker narrow
            # down which.
            raise InvalidTokenError("Invalid or expired invitation token")

        membership = await self._add_member_use_case.execute(
            AddMemberCommand(
                organization_id=invitation.organization_id,
                user_id=command.accepting_user_id,
                role_code=invitation.role_code,
                invited_by=invitation.invited_by,
            )
        )

        invitation.accepted_at = datetime.now(UTC)
        await record_organization_audit_event(
            self._session,
            self._audit_log,
            "organization.invitation.accepted",
            command.accepting_user_id,
            {"organization_id": str(invitation.organization_id)},
        )
        return membership, invitation.role_code
