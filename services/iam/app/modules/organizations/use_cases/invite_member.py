from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.core.cache import PermissionCache
from app.core.config import Settings
from app.modules.organizations.exceptions import (
    OrganizationNotFoundError,
    UserAlreadyMemberError,
)
from app.modules.organizations.models import OrganizationInvitation
from app.modules.organizations.repositories.interfaces.organization_repository import (
    OrganizationInvitationRepository,
    OrganizationRepository,
)
from app.modules.organizations.schemas.commands.invite_member_command import (
    InviteMemberCommand,
)
from app.modules.organizations.use_cases._audit import record_organization_audit_event
from app.modules.organizations.use_cases._grant_guard import ensure_can_grant_role
from app.modules.roles.exceptions import RoleNotFoundError
from app.modules.roles.repositories.interfaces.role_repository import RoleRepository
from app.modules.users.repositories.sqlalchemy.user_repository import UserRepository
from app.shared.security.invitation_token import generate_invitation_token
from app.shared.value_objects import Email
from sqlalchemy.ext.asyncio import AsyncSession


class InviteMemberUseCase:
    """Invite a (possibly not-yet-registered) email to join an org.

    Returns ``(invitation, raw_token)``. ``raw_token`` is only non-None
    in debug by default — there's no email/notification service in this
    $0 stack (same pattern as ``AuthService.request_password_reset``),
    so dev/test environments get the token back directly instead of via
    a delivered email. ``always_reveal_token=True`` (used by the
    POST /tenants/{tenant_id}/invites contract) returns it unconditionally
    instead: that caller is the already-authenticated, already-authorized
    inviter, not an anonymous requester — there's no one else the token
    could leak *to*, unlike e.g. a password-reset response.
    """

    def __init__(
        self,
        session: AsyncSession,
        orgs: OrganizationRepository,
        roles: RoleRepository,
        users: UserRepository,
        invitations: OrganizationInvitationRepository,
        audit_log,
        permission_cache: PermissionCache | None,
        settings: Settings,
    ) -> None:
        self._session = session
        self._orgs = orgs
        self._roles = roles
        self._users = users
        self._invitations = invitations
        self._audit_log = audit_log
        self._permission_cache = permission_cache
        self._settings = settings

    async def execute(self, command: InviteMemberCommand) -> tuple[OrganizationInvitation, str | None]:
        if await self._orgs.get_by_id(command.organization_id) is None:
            raise OrganizationNotFoundError(f"No organization with id '{command.organization_id}'")

        normalized_email = Email(command.email).value

        role = await self._roles.get_by_code_in_org(command.organization_id, command.role_code)
        if role is None:
            raise RoleNotFoundError(f"No role '{command.role_code}' exists in this organization")

        existing_user = await self._users.get_by_email(normalized_email)
        if existing_user is not None and (
            await self._orgs.get_membership(command.organization_id, existing_user.id) is not None
        ):
            raise UserAlreadyMemberError("This user is already a member of this organization")

        await ensure_can_grant_role(
            self._orgs,
            self._roles,
            command.organization_id,
            granter_id=command.invited_by,
            target_role=role,
            permission_cache=self._permission_cache,
        )

        now = datetime.now(UTC)
        # Re-inviting the same email supersedes any still-pending invite
        # rather than accumulating duplicates that could later be accepted
        # against a role chosen at a different time.
        stale = await self._invitations.get_pending_for_org_and_email(
            command.organization_id, normalized_email
        )
        if stale is not None:
            stale.revoked_at = now

        raw_token, token_hash = generate_invitation_token()
        invitation = OrganizationInvitation(
            id=uuid.uuid4(),
            organization_id=command.organization_id,
            email=normalized_email,
            role_code=role.code,
            token_hash=token_hash,
            invited_by=command.invited_by,
            expires_at=now + timedelta(minutes=self._settings.organization_invitation_expire_minutes),
            created_at=now,
        )
        self._invitations.add(invitation)
        await record_organization_audit_event(
            self._session,
            self._audit_log,
            "organization.invitation.created",
            command.invited_by,
            {
                "organization_id": str(command.organization_id),
                "email": normalized_email,
            },
        )
        return invitation, (
            raw_token if (command.always_reveal_token or self._settings.debug) else None
        )
