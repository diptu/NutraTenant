"""Organization lifecycle, membership management, and tenant-level attribute mapping.

Membership is intentionally limited to the roles an organization is
auto-provisioned with at creation (``owner``, ``admin``, ``member``,
``viewer``) — full custom role management is a separate concern (role CRUD)
not built here. ``owner`` stays the one structural role (the bypass in
``_ensure_can_grant_role``, the last-owner protections, ...) — ``admin`` is
just a regular grantable role with no permissions attached by default, not
a second structural tier.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.core.cache import PermissionCache
from app.core.config import Settings, get_settings
from app.domain.exceptions import (
    ForbiddenError,
    InvalidTokenError,
    InvitationNotFoundError,
    LastOwnerError,
    OrganizationAlreadyExistsError,
    OrganizationNotFoundError,
    RoleNotFoundError,
    UserAlreadyMemberError,
    UserNotFoundError,
)
from app.domain.value_objects import Email
from app.infrastructure.db.models.associations import UserOrganizationRole
from app.infrastructure.db.models.audit_log import AuditLog
from app.infrastructure.db.models.organization import Organization
from app.infrastructure.db.models.organization_invitation import (
    OrganizationInvitation,
)
from app.infrastructure.db.models.role import Role
from app.infrastructure.db.repositories.audit_repo import AuditLogRepository
from app.infrastructure.db.repositories.organization_invitation_repo import (
    OrganizationInvitationRepository,
)
from app.infrastructure.db.repositories.organization_repo import OrganizationRepository
from app.infrastructure.db.repositories.role_repo import RoleRepository
from app.infrastructure.db.repositories.user_repo import UserRepository
from app.infrastructure.security.invitation_token import (
    generate_invitation_token,
    hash_invitation_token,
)
from app.services.org_permissions import get_member_permissions
from app.services.role_lookup import (
    DEFAULT_ORG_ROLES,
    provision_role,
    resolve_role_in_org,
)
from sqlalchemy.exc import IntegrityError


def _aware(value: datetime) -> datetime:
    """Postgres' ``DateTime(timezone=True)`` round-trips tz-aware; SQLite (tests
    only) round-trips naive. Normalize before comparing against `datetime.now(UTC)`."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class OrganizationService:
    def __init__(
        self,
        session,
        permission_cache: PermissionCache | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._permission_cache = permission_cache
        self._settings = settings or get_settings()
        self._orgs = OrganizationRepository(session)
        self._roles = RoleRepository(session)
        self._users = UserRepository(session)
        self._invitations = OrganizationInvitationRepository(session)
        self._audit_log = AuditLogRepository(session)

    # -- lifecycle -------------------------------------------------------

    async def create(
        self, *, name: str, slug: str, description: str | None, owner_id: uuid.UUID
    ) -> Organization:
        if await self._orgs.get_by_slug(slug) is not None:
            raise OrganizationAlreadyExistsError(f"Organization slug '{slug}' is already taken")

        now = datetime.now(UTC)
        org = Organization(
            id=uuid.uuid4(),
            name=name,
            slug=slug,
            description=description,
            owner_id=owner_id,
            is_active=True,
            default_attributes={},
            created_at=now,
            updated_at=now,
        )
        self._orgs.add(org)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise OrganizationAlreadyExistsError(f"Organization slug '{slug}' is already taken") from exc

        roles = {code: await self._provision_role(org.id, code, name) for code, name in DEFAULT_ORG_ROLES}

        membership = UserOrganizationRole(
            id=uuid.uuid4(),
            organization_id=org.id,
            user_id=owner_id,
            role_id=roles["owner"].id,
            invited_by=None,
            is_active=True,
            joined_at=now,
            created_at=now,
            updated_at=now,
        )
        self._orgs.add_membership(membership)
        await self._session.commit()
        return org

    async def _provision_role(self, organization_id: uuid.UUID, code: str, name: str) -> Role:
        return await provision_role(self._session, self._roles, organization_id, code=code, name=name)

    async def get(self, organization_id: uuid.UUID) -> Organization:
        org = await self._orgs.get_by_id(organization_id)
        if org is None:
            raise OrganizationNotFoundError(f"No organization with id '{organization_id}'")
        return org

    async def get_by_slug(self, slug: str) -> Organization:
        org = await self._orgs.get_by_slug(slug)
        if org is None:
            raise OrganizationNotFoundError(f"No tenant '{slug}'")
        return org

    async def resolve_role(self, organization_id: uuid.UUID, role: str) -> Role | None:
        """Resolves a free-form role string (a `code` or a display `name`)
        to this organization's Role — see app.services.role_lookup."""
        return await resolve_role_in_org(self._roles, organization_id, role)

    async def list_for_user(self, user_id: uuid.UUID) -> list[Organization]:
        return await self._orgs.list_for_user(user_id)

    async def update(
        self,
        organization_id: uuid.UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        default_attributes: dict | None = None,
    ) -> Organization:
        org = await self.get(organization_id)
        if name is not None:
            org.name = name
        if description is not None:
            org.description = description
        if default_attributes is not None:
            org.default_attributes = default_attributes
        org.updated_at = datetime.now(UTC)
        await self._session.commit()
        return org

    async def delete(self, organization_id: uuid.UUID) -> None:
        org = await self.get(organization_id)
        # Explicit, not relying on ORM cascade: Organization.members has no
        # cascade configured (and deleting it would mean loading the whole
        # collection through a `lazy="raise"` relationship just to cascade),
        # so without this the unit of work tries to null the NOT NULL
        # organization_members.organization_id column instead of deleting
        # those rows.
        for membership in await self._orgs.list_members(organization_id):
            await self._orgs.remove_membership(membership)
        await self._orgs.delete(org)
        await self._session.commit()

    # -- membership -------------------------------------------------------

    async def require_membership(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> UserOrganizationRole:
        membership = await self._orgs.get_membership(organization_id, user_id)
        if membership is None:
            raise ForbiddenError("You are not a member of this organization")
        return membership

    async def require_owner(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> UserOrganizationRole:
        membership = await self.require_membership(organization_id, user_id)
        if membership.role.code != "owner":
            raise ForbiddenError("Only the organization owner can perform this action")
        return membership

    async def list_members(self, organization_id: uuid.UUID) -> list[UserOrganizationRole]:
        await self.get(organization_id)
        return await self._orgs.list_members(organization_id)

    async def _ensure_can_grant_role(
        self, organization_id: uuid.UUID, *, granter_id: uuid.UUID, target_role: Role
    ) -> None:
        """The privilege-escalation guard: granting a role whose permissions
        exceed what the granter themself holds is refused. Reachable today
        via PATCH .../members/{user_id} (open to any member, not just the
        owner) — add_member itself stays owner-or-superuser-gated at the
        route, where this is a defense-in-depth safety net instead.
        """
        granter_membership = await self._orgs.get_membership(organization_id, granter_id)
        if granter_membership is None:
            return  # superuser acting without being a member — already vetted by the route
        if granter_membership.role.code == "owner":
            return

        # "owner" carries no permission *codes* of its own — it's a
        # structural distinction, not a grantable permission set — so the
        # subset check below can't see it. A non-owner must never be able
        # to grant ownership, full stop, regardless of what permissions
        # they hold.
        if target_role.code == "owner":
            raise ForbiddenError("Only the organization owner can grant ownership")

        target_role_with_permissions = await self._roles.get_with_permissions(target_role.id)
        target_codes = {
            p.code for p in (target_role_with_permissions.permissions if target_role_with_permissions else [])
        }
        if not target_codes:
            return

        granter_codes = await get_member_permissions(
            organization_id, granter_membership, cache=self._permission_cache
        )
        if not target_codes.issubset(granter_codes):
            raise ForbiddenError("Cannot grant a role with permissions exceeding your own")

    async def add_member(
        self,
        organization_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        role_code: str = "member",
        invited_by: uuid.UUID | None,
    ) -> UserOrganizationRole:
        org = await self.get(organization_id)

        if await self._orgs.get_membership(organization_id, user_id) is not None:
            raise UserAlreadyMemberError("This user is already a member of this organization")

        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(f"No user with id '{user_id}'")

        role = await self._roles.get_by_code_in_org(organization_id, role_code)
        if role is None:
            raise RoleNotFoundError(f"No role '{role_code}' exists in this organization")

        if invited_by is not None:
            await self._ensure_can_grant_role(organization_id, granter_id=invited_by, target_role=role)

        now = datetime.now(UTC)
        membership = UserOrganizationRole(
            id=uuid.uuid4(),
            organization_id=organization_id,
            user_id=user_id,
            role_id=role.id,
            invited_by=invited_by,
            is_active=True,
            joined_at=now,
            created_at=now,
            updated_at=now,
        )
        self._orgs.add_membership(membership)

        # Tenant-level attribute mapping: fill in any default_attributes key
        # the user doesn't already have — never overwrite a value the user
        # (or a more specific prior grant) already set.
        if org.default_attributes:
            user.attributes = {**org.default_attributes, **(user.attributes or {})}
            user.updated_at = now

        await self._session.commit()
        return membership

    async def remove_member(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> None:
        membership = await self._orgs.get_membership(organization_id, user_id)
        if membership is None:
            raise UserNotFoundError("This user is not a member of this organization")
        if membership.role.code == "owner" and await self._orgs.count_owners(organization_id) <= 1:
            raise LastOwnerError("Cannot remove the organization's last owner")
        await self._orgs.remove_membership(membership)
        await self._session.commit()

    async def update_member_role(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        new_role_code: str,
        actor_id: uuid.UUID,
    ) -> UserOrganizationRole:
        membership = await self._orgs.get_membership(organization_id, user_id)
        if membership is None:
            raise UserNotFoundError("This user is not a member of this organization")

        new_role = await self._roles.get_by_code_in_org(organization_id, new_role_code)
        if new_role is None:
            raise RoleNotFoundError(f"No role '{new_role_code}' exists in this organization")

        await self._ensure_can_grant_role(organization_id, granter_id=actor_id, target_role=new_role)

        if membership.role.code == "owner" and new_role.code != "owner":
            if await self._orgs.count_owners(organization_id) <= 1:
                raise LastOwnerError("Cannot demote the organization's last owner")

        membership.role_id = new_role.id
        membership.updated_at = datetime.now(UTC)
        await self._session.commit()

        # `membership.role` is still the *old* Role object in the session's
        # identity map — changing role_id directly doesn't refresh a
        # selectinload-populated relationship on its own. Expire so the
        # re-fetch below actually reloads it instead of returning the stale
        # cached relationship.
        self._session.expire(membership)
        refreshed = await self._orgs.get_membership(organization_id, user_id)
        assert refreshed is not None
        return refreshed

    # -- invitations -------------------------------------------------------

    async def invite_member(
        self,
        organization_id: uuid.UUID,
        *,
        email: str,
        role_code: str = "member",
        invited_by: uuid.UUID,
        always_reveal_token: bool = False,
    ) -> tuple[OrganizationInvitation, str | None]:
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
        await self.get(organization_id)  # 404s first if the org doesn't exist

        normalized_email = Email(email).value

        role = await self._roles.get_by_code_in_org(organization_id, role_code)
        if role is None:
            raise RoleNotFoundError(f"No role '{role_code}' exists in this organization")

        existing_user = await self._users.get_by_email(normalized_email)
        if existing_user is not None and (
            await self._orgs.get_membership(organization_id, existing_user.id) is not None
        ):
            raise UserAlreadyMemberError("This user is already a member of this organization")

        await self._ensure_can_grant_role(organization_id, granter_id=invited_by, target_role=role)

        now = datetime.now(UTC)
        # Re-inviting the same email supersedes any still-pending invite
        # rather than accumulating duplicates that could later be accepted
        # against a role chosen at a different time.
        stale = await self._invitations.get_pending_for_org_and_email(organization_id, normalized_email)
        if stale is not None:
            stale.revoked_at = now

        raw_token, token_hash = generate_invitation_token()
        invitation = OrganizationInvitation(
            id=uuid.uuid4(),
            organization_id=organization_id,
            email=normalized_email,
            role_code=role.code,
            token_hash=token_hash,
            invited_by=invited_by,
            expires_at=now + timedelta(minutes=self._settings.organization_invitation_expire_minutes),
            created_at=now,
        )
        self._invitations.add(invitation)
        await self._audit(
            event_type="organization.invitation.created",
            user_id=invited_by,
            context={
                "organization_id": str(organization_id),
                "email": normalized_email,
            },
        )
        return invitation, (raw_token if (always_reveal_token or self._settings.debug) else None)

    async def list_pending_invitations(self, organization_id: uuid.UUID) -> list[OrganizationInvitation]:
        await self.get(organization_id)  # 404s first if the org doesn't exist
        return await self._invitations.list_pending_for_org(organization_id)

    async def revoke_invitation(self, organization_id: uuid.UUID, invitation_id: uuid.UUID) -> None:
        invitation = await self._invitations.get_by_id(invitation_id)
        if (
            invitation is None
            or invitation.organization_id != organization_id
            or invitation.accepted_at is not None
            or invitation.revoked_at is not None
        ):
            raise InvitationNotFoundError("No pending invitation with this id")
        invitation.revoked_at = datetime.now(UTC)
        await self._session.commit()

    async def accept_invitation(
        self, *, raw_token: str, accepting_user_id: uuid.UUID, accepting_email: str
    ) -> tuple[UserOrganizationRole, str]:
        invitation = await self._invitations.get_by_token_hash(hash_invitation_token(raw_token))

        if (
            invitation is None
            or invitation.accepted_at is not None
            or invitation.revoked_at is not None
            or _aware(invitation.expires_at) < datetime.now(UTC)
            or invitation.email != Email(accepting_email).value
        ):
            # Same message for "no such token", "already used", "revoked",
            # "expired", and "wrong account" — don't help an attacker narrow
            # down which.
            raise InvalidTokenError("Invalid or expired invitation token")

        membership = await self.add_member(
            invitation.organization_id,
            user_id=accepting_user_id,
            role_code=invitation.role_code,
            invited_by=invitation.invited_by,
        )

        invitation.accepted_at = datetime.now(UTC)
        await self._audit(
            event_type="organization.invitation.accepted",
            user_id=accepting_user_id,
            context={"organization_id": str(invitation.organization_id)},
        )
        return membership, invitation.role_code

    # -- shared helpers ------------------------------------------------------

    async def _audit(self, *, event_type: str, user_id: uuid.UUID | None, context: dict) -> None:
        self._audit_log.add(
            AuditLog(
                id=uuid.uuid4(),
                user_id=user_id,
                event_type=event_type,
                context=context,
                created_at=datetime.now(UTC),
            )
        )
        await self._session.commit()
