"""Registration, password login, refresh-token rotation, and logout.

Orchestration only — persistence goes through the repository layer, token
mechanics through app.modules.auth.utils.jwt, hashing through app.modules.auth.utils.passwords.
The caller (a FastAPI dependency, or a test) owns the session's
commit/rollback boundary; this service only flushes when it needs a
DB-assigned default or a constraint violation to surface before deciding
what to do next.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from app.audit import AuditLogRepository
from app.core.config import Settings
from app.core.rate_limit import RateLimiter
from app.core.token_blacklist import TokenBlacklist
from app.infrastructure.database.associations import UserOrganizationRole
from app.infrastructure.notifications.email_sender import (
    send_invite_email,
    send_tenant_invite_email,
)
from app.modules.auth.exceptions import (
    EmailAlreadyExistsError,
    InvalidTokenError,
    SessionNotFoundError,
    UsernameAlreadyExistsError,
)
from app.modules.auth.models import RefreshToken
from app.modules.auth.repositories.sqlalchemy.token_repository import (
    EmailVerificationTokenRepository,
    PasswordResetTokenRepository,
    RefreshTokenRepository,
)
from app.modules.auth.schemas.commands.change_password_command import ChangePasswordCommand
from app.modules.auth.schemas.commands.confirm_mfa_command import ConfirmMfaCommand
from app.modules.auth.schemas.commands.disable_mfa_command import DisableMfaCommand
from app.modules.auth.schemas.commands.login_command import LoginCommand
from app.modules.auth.schemas.commands.logout_command import LogoutCommand
from app.modules.auth.schemas.commands.refresh_command import RefreshCommand
from app.modules.auth.schemas.commands.register_command import RegisterCommand
from app.modules.auth.schemas.commands.request_password_reset_command import (
    RequestPasswordResetCommand,
)
from app.modules.auth.schemas.commands.reset_password_command import ResetPasswordCommand
from app.modules.auth.schemas.commands.setup_mfa_command import SetupMfaCommand
from app.modules.auth.schemas.commands.switch_tenant_command import SwitchTenantCommand
from app.modules.auth.schemas.commands.verify_mfa_and_login_command import (
    VerifyMfaAndLoginCommand,
)
from app.modules.auth.schemas.dto.login_result_dto import LoginResult
from app.modules.auth.schemas.dto.switch_tenant_result_dto import SwitchTenantResult
from app.modules.auth.schemas.dto.tenant_bootstrap_result_dto import TenantBootstrapResult
from app.modules.auth.schemas.dto.token_pair_dto import TokenPair
from app.modules.auth.use_cases._audit import record_auth_audit_event
from app.modules.auth.use_cases._dates import aware
from app.modules.auth.use_cases._session import issue_new_session as _issue_new_session
from app.modules.auth.use_cases.change_password import ChangePasswordUseCase
from app.modules.auth.use_cases.confirm_mfa import ConfirmMfaUseCase
from app.modules.auth.use_cases.disable_mfa import DisableMfaUseCase
from app.modules.auth.use_cases.login import LoginUseCase
from app.modules.auth.use_cases.logout import LogoutUseCase
from app.modules.auth.use_cases.refresh import RefreshUseCase
from app.modules.auth.use_cases.register import RegisterUseCase
from app.modules.auth.use_cases.request_password_reset import RequestPasswordResetUseCase
from app.modules.auth.use_cases.reset_password import ResetPasswordUseCase
from app.modules.auth.use_cases.setup_mfa import SetupMfaUseCase
from app.modules.auth.use_cases.switch_tenant import SwitchTenantUseCase
from app.modules.auth.use_cases.verify_mfa_and_login import VerifyMfaAndLoginUseCase
from app.modules.auth.utils.passwords import hash_password
from app.modules.auth.utils.tokens import hash_verification_token
from app.modules.organizations.exceptions import (
    OrganizationAlreadyExistsError,
    OrganizationNotFoundError,
)
from app.modules.organizations.models import Organization, OrganizationInvitation
from app.modules.organizations.repositories.sqlalchemy.organization_repository import (
    OrganizationInvitationRepository,
    OrganizationRepository,
)
from app.modules.reserved_tenant_ids.exceptions import ReservedTenantIdError
from app.modules.reserved_tenant_ids.repositories.sqlalchemy.reserved_tenant_id_repository import (
    ReservedTenantIdRepository,
)
from app.modules.roles.exceptions import RoleNotFoundError
from app.modules.roles.models import Role
from app.modules.roles.repositories.sqlalchemy.role_repository import RoleRepository
from app.modules.roles.service import DEFAULT_ORG_ROLES, provision_role, resolve_role_in_org
from app.modules.users.models import User
from app.modules.users.repositories.sqlalchemy.user_repository import UserRepository
from app.shared.security.invitation_token import generate_invitation_token, hash_invitation_token
from app.shared.utils.base_service import BaseService
from app.shared.value_objects import Email
from sqlalchemy.exc import IntegrityError

__all__ = [
    "AuthService",
    "LoginResult",
    "SwitchTenantResult",
    "TenantBootstrapResult",
    "TokenPair",
]


class AuthService(BaseService):
    def __init__(
        self,
        session,
        settings: Settings,
        token_blacklist: TokenBlacklist,
        rate_limiter: RateLimiter,
    ) -> None:
        super().__init__(session)
        self._settings = settings
        self._token_blacklist = token_blacklist
        self._rate_limiter = rate_limiter
        self._users = UserRepository(session)
        self._refresh_tokens = RefreshTokenRepository(session)
        self._reset_tokens = PasswordResetTokenRepository(session)
        self._verification_tokens = EmailVerificationTokenRepository(session)
        self._audit_log = AuditLogRepository(session)
        self._orgs = OrganizationRepository(session)
        self._roles = RoleRepository(session)
        self._invitations = OrganizationInvitationRepository(session)
        self._reserved_tenant_ids = ReservedTenantIdRepository(session)
        self._register_use_case = RegisterUseCase(
            session, settings, self._users, self._verification_tokens, self._audit_log
        )
        self._login_use_case = LoginUseCase(
            session, settings, rate_limiter, self._users, self._orgs, self._refresh_tokens, self._audit_log
        )
        self._verify_mfa_and_login_use_case = VerifyMfaAndLoginUseCase(
            session,
            settings,
            token_blacklist,
            rate_limiter,
            self._users,
            self._orgs,
            self._refresh_tokens,
            self._audit_log,
        )
        self._switch_tenant_use_case = SwitchTenantUseCase(
            session, settings, self._orgs, self._refresh_tokens, self._audit_log
        )
        self._refresh_use_case = RefreshUseCase(
            session, settings, self._orgs, self._refresh_tokens, self._audit_log
        )
        self._logout_use_case = LogoutUseCase(
            session, settings, token_blacklist, self._refresh_tokens, self._audit_log
        )
        self._change_password_use_case = ChangePasswordUseCase(
            session, settings, token_blacklist, self._users, self._refresh_tokens, self._audit_log
        )
        self._request_password_reset_use_case = RequestPasswordResetUseCase(
            session, settings, self._users, self._reset_tokens, self._audit_log
        )
        self._reset_password_use_case = ResetPasswordUseCase(
            session,
            settings,
            token_blacklist,
            self._users,
            self._reset_tokens,
            self._refresh_tokens,
            self._audit_log,
        )
        self._setup_mfa_use_case = SetupMfaUseCase(session, settings, self._users, self._audit_log)
        self._confirm_mfa_use_case = ConfirmMfaUseCase(session, settings, self._users, self._audit_log)
        self._disable_mfa_use_case = DisableMfaUseCase(session, settings, self._users, self._audit_log)

    # -- registration ----------------------------------------------------

    async def register(self, *, email: str, password: str, full_name: str | None) -> tuple[User, str | None]:
        command = RegisterCommand(email=email, password=password, full_name=full_name)
        return await self._register_use_case.execute(command)

    async def verify_email(self, raw_token: str) -> datetime:
        """Returns the verification timestamp. Mirrors ``reset_password``'s
        token lookup: the same error/message for "no such token", "already
        used", and "expired" — don't help an attacker narrow down which."""
        token_row = await self._verification_tokens.get_by_token_hash(hash_verification_token(raw_token))
        if (
            token_row is None
            or token_row.used_at is not None
            or aware(token_row.expires_at) < datetime.now(UTC)
        ):
            raise InvalidTokenError("Invalid or expired verification token")

        user = await self._users.get_by_id(token_row.user_id)
        if user is None:
            raise InvalidTokenError("Invalid or expired verification token")

        now = datetime.now(UTC)
        user.is_verified = True
        user.updated_at = now
        token_row.used_at = now

        await record_auth_audit_event(self._session, self._audit_log, "auth.email.verified", user.id, {})
        return now

    # -- tenant invitation acceptance (no prior account/session) -----------

    async def accept_invite(
        self, *, invite_token: str, name: str | None, password: str
    ) -> tuple[User, Organization, Role]:
        """Self-service signup via a tenant invitation token — unlike
        ``OrganizationService.accept_invitation``, this assumes the invitee
        has *no authenticated session* yet: it creates (or completes) the
        user, the org membership, and marks the invitation consumed all in
        the one commit ``_audit`` makes at the end, so a crash partway
        through never leaves a membership without its invitation marked
        accepted (or vice versa) — single atomic transaction, not two.

        ``existing_user`` here covers two different cases:
        - A *real* account (``password_hash`` already set) — rejected.
          Letting this endpoint set a password for an email that already
          has working credentials would be a silent account-takeover
          primitive: anyone holding a valid invite for someone else's email
          could overwrite their password without ever authenticating as
          them. A real account must accept via the authenticated
          POST /organizations/invitations/accept instead.
        - A *skeleton* account with no password yet (created by
          ``AuthService.create_tenant`` for a not-yet-registered owner) —
          completed in place rather than rejected, since it was never a
          usable account to begin with.
        """
        invitation = await self._invitations.get_by_token_hash(hash_invitation_token(invite_token))
        if (
            invitation is None
            or invitation.accepted_at is not None
            or invitation.revoked_at is not None
            or aware(invitation.expires_at) < datetime.now(UTC)
        ):
            # Same message for every failure mode — don't help an attacker
            # narrow down which, same convention as password-reset tokens.
            raise InvalidTokenError("Invalid or expired invitation token")

        existing_user = await self._users.get_by_email(invitation.email)
        if existing_user is not None and existing_user.password_hash is not None:
            raise EmailAlreadyExistsError(
                f"'{invitation.email}' already has an account — log in and "
                "accept this invitation from your account instead"
            )

        organization = await self._orgs.get_by_id(invitation.organization_id)
        if organization is None:
            raise OrganizationNotFoundError("This invitation's organization no longer exists")

        role = await self._roles.get_by_code_in_org(invitation.organization_id, invitation.role_code)
        if role is None:
            raise RoleNotFoundError(f"No role '{invitation.role_code}' exists in this organization")

        now = datetime.now(UTC)
        if existing_user is not None:
            # Complete the skeleton profile in place.
            user = existing_user
            user.full_name = name or user.full_name
            user.password_hash = hash_password(password)
            # Redeeming a token sent to a specific email is itself proof of
            # mailbox control — equivalent to clicking a verification link.
            user.is_verified = True
            user.updated_at = now
            user.password_changed_at = now
        else:
            user = User(
                id=uuid.uuid4(),
                email=invitation.email,
                full_name=name,
                password_hash=hash_password(password),
                attributes=dict(organization.default_attributes or {}),
                is_active=True,
                is_verified=True,
                is_superuser=False,
                failed_login_count=0,
                created_at=now,
                updated_at=now,
                password_changed_at=now,
            )
            self._users.add(user)
            try:
                await self._session.flush()
            except IntegrityError as exc:
                raise EmailAlreadyExistsError(f"'{invitation.email}' is already registered") from exc

        # A skeleton owner from AuthService.create_tenant is already mapped
        # into the org (Phase D happens at tenant-creation time, before any
        # invite is redeemed) — don't insert a second, conflicting row.
        membership = await self._orgs.get_membership(invitation.organization_id, user.id)
        if membership is None:
            membership = UserOrganizationRole(
                id=uuid.uuid4(),
                organization_id=invitation.organization_id,
                user_id=user.id,
                role_id=role.id,
                invited_by=invitation.invited_by,
                is_active=True,
                joined_at=now,
                created_at=now,
                updated_at=now,
            )
            self._session.add(membership)
        invitation.accepted_at = now

        await record_auth_audit_event(
            self._session,
            self._audit_log,
            "organization.invitation.accepted",
            user.id,
            {"organization_id": str(invitation.organization_id)},
        )
        return user, organization, role

    # -- admin provisioning --------------------------------------------------

    async def provision_user(
        self,
        *,
        email: str,
        full_name: str | None,
        tenant_slug: str,
        role: str,
        username: str | None = None,
        phone: str | None = None,
        attributes: dict | None = None,
    ) -> tuple[User, Organization, Role, str]:
        """Admin-provisions a user directly into a tenant — no invite round
        trip. The account is never left without a password (a temp one is
        generated here); ``must_change_password`` forces it to be replaced
        on first real use. Delivery of the temp password is a stub (see
        app.infrastructure.notifications.email_sender) since there's no real
        email provider wired up yet — same "not built yet" situation as
        every other token/credential delivery path in this service.

        ``attributes`` (caller-supplied ABAC values, e.g. department/
        designation) are merged over the organization's default_attributes
        template — same precedence as OrganizationService.add_member: the
        more specific, explicitly-given value wins over the tenant default.

        Returns ``(user, organization, role, temp_password)`` — the temp
        password is for the email stub/caller's own use, never echoed back
        over the API response itself.
        """
        normalized_email = Email(email).value
        if await self._users.get_by_email(normalized_email) is not None:
            raise EmailAlreadyExistsError(f"'{normalized_email}' is already registered")

        if username is not None and await self._users.get_by_username(username) is not None:
            raise UsernameAlreadyExistsError(f"Username '{username}' is already taken")

        organization = await self._orgs.get_by_slug(tenant_slug)
        if organization is None:
            raise OrganizationNotFoundError(f"No tenant '{tenant_slug}'")

        resolved_role = await resolve_role_in_org(self._roles, organization.id, role)
        if resolved_role is None:
            raise RoleNotFoundError(f"No role '{role}' exists in tenant '{tenant_slug}'")

        temp_password = secrets.token_urlsafe(12)
        now = datetime.now(UTC)
        user = User(
            id=uuid.uuid4(),
            email=normalized_email,
            full_name=full_name,
            username=username,
            phone=phone,
            password_hash=hash_password(temp_password),
            attributes={**(organization.default_attributes or {}), **(attributes or {})},
            is_active=True,
            is_verified=False,
            is_superuser=False,
            failed_login_count=0,
            must_change_password=True,
            created_at=now,
            updated_at=now,
            password_changed_at=now,
        )
        self._users.add(user)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if username is not None:
                raise UsernameAlreadyExistsError(f"Username '{username}' is already taken") from exc
            raise EmailAlreadyExistsError(f"'{normalized_email}' is already registered") from exc

        membership = UserOrganizationRole(
            id=uuid.uuid4(),
            organization_id=organization.id,
            user_id=user.id,
            role_id=resolved_role.id,
            invited_by=None,
            is_active=True,
            joined_at=now,
            created_at=now,
            updated_at=now,
        )
        self._session.add(membership)

        await send_invite_email(
            to=normalized_email,
            temp_password=temp_password,
            tenant_name=organization.name,
        )

        await record_auth_audit_event(
            self._session,
            self._audit_log,
            "user.admin_provisioned",
            user.id,
            {"organization_id": str(organization.id)},
        )
        return user, organization, resolved_role, temp_password

    # -- tenant bootstrap (root tenant-creation API) ------------------------

    async def create_tenant(
        self,
        *,
        name: str,
        tenant_id: str,
        owner_email: str,
        plan: str = "free",
        settings: dict | None = None,
        metadata: dict | None = None,
    ) -> TenantBootstrapResult:
        """Provisions a brand-new tenant end to end: the org row, its
        standard role set, the owner's membership, and — if the owner's
        email has no existing account — a skeleton user row plus an invite
        token to complete it. All in the one commit ``_audit`` makes at the
        end, so a failure anywhere rolls back the whole thing; no orphaned
        tenant, no role set without an owner.

        Note on ordering vs. the conceptual A→B→C→D phases this mirrors:
        the owner user row is resolved/created *before* the Organization
        row here, not after — `Organization.owner_id` is a NOT NULL FK, so
        a brand-new owner has to exist first. Everything still lands in the
        same single transaction either way.
        """
        if await self._reserved_tenant_ids.get_by_tenant_id(tenant_id) is not None:
            raise ReservedTenantIdError(f"tenant_id '{tenant_id}' is reserved and cannot be used")
        if await self._orgs.get_by_slug(tenant_id) is not None:
            raise OrganizationAlreadyExistsError(f"Tenant '{tenant_id}' already exists")

        normalized_email = Email(owner_email).value
        owner = await self._users.get_by_email(normalized_email)
        is_new_owner = owner is None

        now = datetime.now(UTC)
        if owner is None:
            # Skeleton profile — no password yet, not verified. Completed
            # via POST /auth/accept-invite, same as any other invitation
            # (see the skeleton-user branch in AuthService.accept_invite).
            owner = User(
                id=uuid.uuid4(),
                email=normalized_email,
                full_name=None,
                password_hash=None,
                attributes={},
                is_active=True,
                is_verified=False,
                is_superuser=False,
                failed_login_count=0,
                created_at=now,
                updated_at=now,
            )
            self._users.add(owner)
            await self._session.flush()

        org = Organization(
            id=uuid.uuid4(),
            name=name,
            slug=tenant_id,
            description=None,
            owner_id=owner.id,
            is_active=True,
            default_attributes={},
            plan=plan,
            settings=settings or {},
            extra_metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )
        self._orgs.add(org)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise OrganizationAlreadyExistsError(f"Tenant '{tenant_id}' already exists") from exc

        roles = {
            code: await provision_role(self._session, self._roles, org.id, code=code, name=display_name)
            for code, display_name in DEFAULT_ORG_ROLES
        }
        owner_role = roles["owner"]

        membership = UserOrganizationRole(
            id=uuid.uuid4(),
            organization_id=org.id,
            user_id=owner.id,
            role_id=owner_role.id,
            invited_by=None,
            is_active=True,
            joined_at=now,
            created_at=now,
            updated_at=now,
        )
        self._session.add(membership)

        invite_token: str | None = None
        if is_new_owner:
            raw_token, token_hash = generate_invitation_token()
            invite_token = raw_token
            invitation = OrganizationInvitation(
                id=uuid.uuid4(),
                organization_id=org.id,
                email=normalized_email,
                role_code=owner_role.code,
                token_hash=token_hash,
                invited_by=None,
                expires_at=now + timedelta(minutes=self._settings.organization_invitation_expire_minutes),
                created_at=now,
            )
            self._invitations.add(invitation)
            await send_tenant_invite_email(to=normalized_email, invite_token=raw_token, tenant_name=name)

        await record_auth_audit_event(
            self._session,
            self._audit_log,
            "tenant.created",
            owner.id,
            {"organization_id": str(org.id), "new_owner": is_new_owner},
        )
        return TenantBootstrapResult(
            organization=org,
            owner=owner,
            owner_role=owner_role,
            is_new_owner=is_new_owner,
            invite_token=invite_token,
        )

    # -- password login ----------------------------------------------------

    async def login(
        self,
        *,
        email: str,
        password: str,
        ip_address: str | None,
        user_agent: str | None,
        tenant_id: str | None = None,
    ) -> LoginResult:
        command = LoginCommand(
            email=email, password=password, ip_address=ip_address, user_agent=user_agent, tenant_id=tenant_id
        )
        return await self._login_use_case.execute(command)

    async def verify_mfa_and_login(
        self,
        *,
        mfa_challenge_token: str,
        code: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> LoginResult:
        command = VerifyMfaAndLoginCommand(
            mfa_challenge_token=mfa_challenge_token,
            code=code,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return await self._verify_mfa_and_login_use_case.execute(command)

    # -- tenant switching --------------------------------------------------

    async def switch_tenant(
        self,
        *,
        user: User,
        tenant_slug: str,
        ip_address: str | None,
        user_agent: str | None,
        current_refresh_token: str | None,
    ) -> SwitchTenantResult:
        command = SwitchTenantCommand(
            user=user,
            tenant_slug=tenant_slug,
            ip_address=ip_address,
            user_agent=user_agent,
            current_refresh_token=current_refresh_token,
        )
        return await self._switch_tenant_use_case.execute(command)

    # -- MFA enrollment ---------------------------------------------------

    async def setup_mfa(self, *, user_id: uuid.UUID) -> tuple[str, str]:
        return await self._setup_mfa_use_case.execute(SetupMfaCommand(user_id=user_id))

    async def confirm_mfa(self, *, user_id: uuid.UUID, code: str) -> list[str]:
        return await self._confirm_mfa_use_case.execute(ConfirmMfaCommand(user_id=user_id, code=code))

    async def disable_mfa(self, *, user_id: uuid.UUID, current_password: str, code: str) -> None:
        command = DisableMfaCommand(user_id=user_id, current_password=current_password, code=code)
        await self._disable_mfa_use_case.execute(command)

    async def issue_new_session(
        self,
        user: User,
        *,
        ip_address: str | None,
        user_agent: str | None,
        organization: Organization | None = None,
    ) -> TokenPair:
        """Start a brand-new rotation family — used by password login, the
        post-MFA verify step, and the Google OIDC callback once an identity
        has been resolved to a user. ``organization`` is omitted by the
        Google flow today (it has no tenant-resolution step yet)."""
        return await _issue_new_session(
            self._session,
            self._settings,
            self._refresh_tokens,
            user,
            ip_address=ip_address,
            user_agent=user_agent,
            organization=organization,
        )

    # -- refresh token rotation ---------------------------------------------

    async def refresh(
        self, *, refresh_token: str, ip_address: str | None, user_agent: str | None
    ) -> TokenPair:
        command = RefreshCommand(refresh_token=refresh_token, ip_address=ip_address, user_agent=user_agent)
        return await self._refresh_use_case.execute(command)

    # -- logout --------------------------------------------------------------

    async def logout(self, *, refresh_token: str | None, access_token: str | None) -> None:
        command = LogoutCommand(refresh_token=refresh_token, access_token=access_token)
        await self._logout_use_case.execute(command)

    # -- session management -----------------------------------------------

    async def list_sessions(self, user_id: uuid.UUID) -> list[RefreshToken]:
        """Each row in `refresh_tokens` *is* a session record (see
        RefreshToken) — active means not revoked and not yet expired."""
        tokens = await self._refresh_tokens.list_active_for_user(user_id)
        now = datetime.now(UTC)
        return [token for token in tokens if aware(token.expires_at) > now]

    async def revoke_session(self, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
        """Revokes one session (DELETE /users/{user_id}/sessions/{session_id})
        without touching the rest of its rotation family's *history* — unlike
        logout/revoke_all_for_user, this targets exactly one still-active
        refresh token. Same 404 regardless of *why* it doesn't match (wrong
        user, already revoked, expired, or doesn't exist) — no signal leaked
        either way."""
        token = await self._refresh_tokens.get_by_id(session_id)
        if (
            token is None
            or token.user_id != user_id
            or token.revoked_at is not None
            or aware(token.expires_at) <= datetime.now(UTC)
        ):
            raise SessionNotFoundError(f"No active session '{session_id}' for this user")
        token.revoked_at = datetime.now(UTC)
        await record_auth_audit_event(self._session, self._audit_log, "auth.session.revoked", user_id, {})
        await self._session.commit()

    # -- password management ---------------------------------------------------

    async def change_password(self, *, user_id: uuid.UUID, current_password: str, new_password: str) -> None:
        command = ChangePasswordCommand(
            user_id=user_id, current_password=current_password, new_password=new_password
        )
        await self._change_password_use_case.execute(command)

    async def request_password_reset(self, *, email: str) -> str | None:
        command = RequestPasswordResetCommand(email=email)
        return await self._request_password_reset_use_case.execute(command)

    async def reset_password(self, *, raw_token: str, new_password: str) -> None:
        command = ResetPasswordCommand(raw_token=raw_token, new_password=new_password)
        await self._reset_password_use_case.execute(command)
