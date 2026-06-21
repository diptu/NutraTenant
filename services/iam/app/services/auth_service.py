"""Registration, password login, refresh-token rotation, and logout.

Orchestration only — persistence goes through the repository layer, token
mechanics through app.infrastructure.security.jwt, hashing through
app.infrastructure.security.password. The caller (a FastAPI dependency,
or a test) owns the session's commit/rollback boundary; this service only
flushes when it needs a DB-assigned default or a constraint violation to
surface before deciding what to do next.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.core.rate_limit import RateLimiter
from app.core.token_blacklist import TokenBlacklist
from app.domain.exceptions import (
    AccountLockedError,
    EmailAlreadyExistsError,
    ForbiddenError,
    InvalidCredentialsError,
    InvalidMfaCodeError,
    InvalidTokenError,
    MfaAlreadyEnabledError,
    MfaNotEnabledError,
    OrganizationAlreadyExistsError,
    OrganizationNotFoundError,
    RateLimitExceededError,
    RefreshTokenReusedError,
    RoleNotFoundError,
    SessionNotFoundError,
    TenantSelectionRequiredError,
    UsernameAlreadyExistsError,
    UserNotFoundError,
)
from app.domain.value_objects import Email
from app.infrastructure.db.models.associations import UserOrganizationRole
from app.infrastructure.db.models.audit_log import AuditLog
from app.infrastructure.db.models.organization import Organization
from app.infrastructure.db.models.organization_invitation import (
    OrganizationInvitation,
)
from app.infrastructure.db.models.password_reset_token import PasswordResetToken
from app.infrastructure.db.models.refresh_token import RefreshToken
from app.infrastructure.db.models.role import Role
from app.infrastructure.db.models.user import User
from app.infrastructure.db.repositories.audit_repo import AuditLogRepository
from app.infrastructure.db.repositories.organization_invitation_repo import (
    OrganizationInvitationRepository,
)
from app.infrastructure.db.repositories.organization_repo import OrganizationRepository
from app.infrastructure.db.repositories.password_reset_token_repo import (
    PasswordResetTokenRepository,
)
from app.infrastructure.db.repositories.refresh_token_repo import RefreshTokenRepository
from app.infrastructure.db.repositories.role_repo import RoleRepository
from app.infrastructure.db.repositories.user_repo import UserRepository
from app.infrastructure.notifications.email_sender import (
    send_invite_email,
    send_tenant_invite_email,
)
from app.infrastructure.security.invitation_token import (
    generate_invitation_token,
    hash_invitation_token,
)
from app.infrastructure.security.jwt import (
    create_access_token,
    create_mfa_challenge_token,
    create_refresh_token,
    decode_access_token,
    decode_mfa_challenge_token,
    decode_refresh_token,
)
from app.infrastructure.security.mfa import (
    build_otpauth_uri,
    decrypt_secret,
    encrypt_secret,
    generate_recovery_codes,
    generate_totp_secret,
    hash_recovery_code,
    verify_totp_code,
)
from app.infrastructure.security.password import hash_password, verify_password
from app.infrastructure.security.reset_token import (
    generate_reset_token,
    hash_reset_token,
)
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


# Per-challenge-token cap on OTP attempts (distinct from the per-account
# `mfa-verify:{user.id}` limiter) — see AuthService.verify_mfa_and_login.
_MFA_CHALLENGE_MAX_ATTEMPTS = 3


def _mfa_challenge_blacklist_key(jti: uuid.UUID) -> str:
    """Namespaced so a challenge token's jti can never collide with an
    access token's jti in the shared TokenBlacklist keyspace."""
    return f"mfa-challenge:{jti}"


@dataclass(frozen=True, slots=True)
class TokenPair:
    """The output of one token-pair issuance — login, post-MFA verify, or a
    refresh rotation. ``session_id`` is the new refresh token's own ``jti``;
    there's no separate sessions table, the refresh_tokens row *is* the
    durable session record (see RefreshToken)."""

    access_token: str
    refresh_token: str
    session_id: uuid.UUID
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class LoginResult:
    """Either a completed login (``access_token``/``refresh_token`` set) or
    an MFA challenge (``mfa_challenge_token`` set) the caller must redeem via
    ``AuthService.verify_mfa_and_login`` before getting real tokens.

    ``organization``/``role``/``permissions`` describe the tenant context the
    session was bound to (see ``AuthService._resolve_tenant``) — all empty
    when the account belongs to no organization. ``previous_last_login_at``
    is the user's last-login timestamp *before* this one, for display only.
    """

    user: User
    mfa_required: bool
    access_token: str | None = None
    refresh_token: str | None = None
    mfa_challenge_token: str | None = None
    organization: Organization | None = None
    role: Role | None = None
    permissions: list[str] = field(default_factory=list)
    session_id: uuid.UUID | None = None
    session_issued_at: datetime | None = None
    session_expires_at: datetime | None = None
    previous_last_login_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SwitchTenantResult:
    """``refresh_token`` is only set when the caller had a still-valid
    refresh token to rotate forward into the new tenant context (see
    ``AuthService.switch_tenant``) — ``None`` doesn't mean failure, just
    that there was nothing to rotate."""

    access_token: str
    refresh_token: str | None
    organization: Organization
    role: Role


@dataclass(frozen=True, slots=True)
class TenantBootstrapResult:
    """``invite_token`` is only set when ``is_new_owner`` is True — an
    already-existing owner is mapped into the new tenant immediately, with
    nothing to redeem (see ``AuthService.create_tenant``)."""

    organization: Organization
    owner: User
    owner_role: Role
    is_new_owner: bool
    invite_token: str | None


class AuthService:
    def __init__(
        self,
        session,
        settings: Settings,
        token_blacklist: TokenBlacklist,
        rate_limiter: RateLimiter,
    ) -> None:
        self._session = session
        self._settings = settings
        self._token_blacklist = token_blacklist
        self._rate_limiter = rate_limiter
        self._users = UserRepository(session)
        self._refresh_tokens = RefreshTokenRepository(session)
        self._reset_tokens = PasswordResetTokenRepository(session)
        self._audit_log = AuditLogRepository(session)
        self._orgs = OrganizationRepository(session)
        self._roles = RoleRepository(session)
        self._invitations = OrganizationInvitationRepository(session)

    # -- registration ----------------------------------------------------

    async def register(self, *, email: str, password: str, full_name: str | None) -> User:
        normalized_email = Email(email).value

        if await self._users.get_by_email(normalized_email) is not None:
            raise EmailAlreadyExistsError(f"'{normalized_email}' is already registered")

        now = datetime.now(UTC)
        user = User(
            id=uuid.uuid4(),
            email=normalized_email,
            full_name=full_name,
            password_hash=hash_password(password),
            attributes={},
            is_active=True,
            is_verified=False,
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
            raise EmailAlreadyExistsError(f"'{normalized_email}' is already registered") from exc

        await self._audit(event_type="user.registered", user_id=user.id, context={})
        return user

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
            or _aware(invitation.expires_at) < datetime.now(UTC)
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

        await self._audit(
            event_type="organization.invitation.accepted",
            user_id=user.id,
            context={"organization_id": str(invitation.organization_id)},
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

        await self._audit(
            event_type="user.admin_provisioned",
            user_id=user.id,
            context={"organization_id": str(organization.id)},
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

        await self._audit(
            event_type="tenant.created",
            user_id=owner.id,
            context={"organization_id": str(org.id), "new_owner": is_new_owner},
        )
        return TenantBootstrapResult(
            organization=org,
            owner=owner,
            owner_role=owner_role,
            is_new_owner=is_new_owner,
            invite_token=invite_token,
        )

    # -- tenant resolution -------------------------------------------------

    async def _resolve_tenant(
        self, user_id: uuid.UUID, tenant_id: str | None
    ) -> tuple[Organization | None, UserOrganizationRole | None]:
        """Picks which organization (if any) a session is bound to.

        ``tenant_id`` is the organization's *slug* (e.g. ``"apple_corp"``),
        not its primary key — matching the `tenant_id` claim already embedded
        on the access token and every other `tenant_id` field on the wire
        (``TenantOut.tenant_id``, the invite/admin/switch-tenant endpoints).

        - ``tenant_id`` given: must be one of the user's memberships, else
          ``ForbiddenError`` (403) — the org exists, the account just can't
          log into it.
        - No ``tenant_id``, zero memberships: no tenant context at all (e.g.
          a superuser or a user who hasn't joined an org yet) — not an error.
        - No ``tenant_id``, exactly one membership: auto-selected.
        - No ``tenant_id``, multiple memberships: ``TenantSelectionRequiredError``
          (409) carrying the list to retry the login with.
        """
        organizations = await self._orgs.list_for_user(user_id)

        if tenant_id is not None:
            organization = next((o for o in organizations if o.slug == tenant_id), None)
            if organization is None:
                raise ForbiddenError("You are not a member of this organization")
        elif not organizations:
            return None, None
        elif len(organizations) == 1:
            organization = organizations[0]
        else:
            raise TenantSelectionRequiredError(
                organizations=[{"id": str(o.id), "tenant_id": o.slug, "name": o.name} for o in organizations]
            )

        membership = await self._orgs.get_membership(organization.id, user_id)
        assert membership is not None  # list_for_user already proved membership
        return organization, membership

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
        normalized_email = Email(email).value

        # Per-email, not global — one attacker hammering one account can't
        # lock everyone else out of attempting their own (correct) login.
        rate_limit = await self._rate_limiter.hit(
            f"login:{normalized_email}",
            limit=self._settings.rate_limit_max_requests,
            window_seconds=self._settings.rate_limit_window_seconds,
        )
        if not rate_limit.allowed:
            await self._audit(
                event_type="auth.login.rate_limited",
                user_id=None,
                ip_address=ip_address,
                user_agent=user_agent,
                context={"email": normalized_email},
            )
            raise RateLimitExceededError(retry_after_seconds=rate_limit.retry_after_seconds)

        user = await self._users.get_by_email(normalized_email)

        if user is None or user.password_hash is None:
            # Same error for "no such user" and "OAuth-only account" — don't
            # let a login attempt enumerate which accounts exist or how
            # they authenticate.
            raise InvalidCredentialsError("Invalid email or password")

        if user.locked_until is not None and _aware(user.locked_until) > datetime.now(UTC):
            retry_after = int((_aware(user.locked_until) - datetime.now(UTC)).total_seconds())
            raise AccountLockedError(retry_after_seconds=max(retry_after, 1))

        if not verify_password(password, user.password_hash):
            await self._record_failed_login(user, ip_address=ip_address, user_agent=user_agent)
            raise InvalidCredentialsError("Invalid email or password")

        # Resolved (and any TenantSelectionRequiredError/ForbiddenError
        # raised) before mutating any user state below — the request-scoped
        # session rolls back on the exception either way, but this keeps
        # "did this attempt even get past tenant resolution" unambiguous.
        organization, membership = await self._resolve_tenant(user.id, tenant_id)

        user.failed_login_count = 0
        user.locked_until = None
        # Only the brute-force lock auto-clears on a correct password —
        # an admin-set SUSPENDED/INACTIVE/DELETED (PATCH .../status) must
        # stay exactly as the admin left it.
        if user.status == "LOCKED":
            user.status = "ACTIVE"
        user.updated_at = datetime.now(UTC)

        if user.mfa_enabled:
            mfa_challenge_token = create_mfa_challenge_token(
                self._settings,
                user_id=user.id,
                organization_id=organization.id if organization else None,
            )
            await self._audit(
                event_type="auth.login.mfa_challenge_issued",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                context={},
            )
            return LoginResult(
                user=user,
                mfa_required=True,
                mfa_challenge_token=mfa_challenge_token,
            )

        # Login is actually completing now (no MFA step pending) — this is
        # the point a "last login" should be recorded, not the password step
        # above, so an MFA-pending attempt never counts as a completed login.
        previous_last_login_at = user.last_login_at
        user.last_login_at = datetime.now(UTC)

        role = membership.role if membership else None
        token_pair = await self.issue_new_session(
            user,
            ip_address=ip_address,
            user_agent=user_agent,
            organization=organization,
            role=role,
        )
        await self._audit(
            event_type="auth.login.success",
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            context={"organization_id": str(organization.id) if organization else None},
        )
        return LoginResult(
            user=user,
            mfa_required=False,
            access_token=token_pair.access_token,
            refresh_token=token_pair.refresh_token,
            organization=organization,
            role=role,
            permissions=sorted(p.code for p in role.permissions) if role else [],
            session_id=token_pair.session_id,
            session_issued_at=token_pair.issued_at,
            session_expires_at=token_pair.expires_at,
            previous_last_login_at=previous_last_login_at,
        )

    async def verify_mfa_and_login(
        self,
        *,
        mfa_challenge_token: str,
        code: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> LoginResult:
        """Redeems an MFA challenge token (from ``login``) plus a TOTP/
        recovery code for a real access/refresh token pair.

        Two independent protections beyond just checking the code, both
        scoped to *this one challenge* (not the account generally — that's
        the separate ``mfa-verify:{user.id}`` limiter below):

        - Single-use: the challenge's ``jti`` is blacklisted the moment it's
          successfully redeemed, so a captured-but-already-used challenge
          token can never be replayed even though it remains cryptographically
          valid until its own ``exp``.
        - Per-challenge lockout: at most ``_MFA_CHALLENGE_MAX_ATTEMPTS``
          attempts against one challenge; the next one blacklists the ``jti``
          outright (a hard lock, not a "retry after N seconds" throttle —
          retrying never helps once a challenge is locked).
        """
        claims = decode_mfa_challenge_token(self._settings, mfa_challenge_token)

        challenge_key = _mfa_challenge_blacklist_key(claims.jti)
        if await self._token_blacklist.contains_jti(challenge_key):
            raise InvalidTokenError("MFA challenge has already been used or has been locked")

        user = await self._users.get_by_id(claims.subject_id)
        if user is None or not user.is_active or not user.mfa_enabled:
            raise InvalidTokenError("Invalid or expired MFA challenge")

        # Per-account, not global — same reasoning as the password-login
        # rate limit: bounds brute-forcing a 6-digit TOTP/recovery code
        # without letting one attacker lock out anyone else's attempts.
        rate_limit = await self._rate_limiter.hit(
            f"mfa-verify:{user.id}",
            limit=self._settings.rate_limit_max_requests,
            window_seconds=self._settings.rate_limit_window_seconds,
        )
        if not rate_limit.allowed:
            raise RateLimitExceededError(retry_after_seconds=rate_limit.retry_after_seconds)

        challenge_ttl_seconds = self._settings.mfa_challenge_token_expire_minutes * 60
        challenge_attempts = await self._rate_limiter.hit(
            f"mfa-challenge-attempts:{claims.jti}",
            limit=_MFA_CHALLENGE_MAX_ATTEMPTS,
            window_seconds=challenge_ttl_seconds,
        )
        if not challenge_attempts.allowed:
            await self._token_blacklist.add_jti(challenge_key, ttl_seconds=challenge_ttl_seconds)
            await self._audit(
                event_type="auth.mfa.challenge_locked",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                context={"max_attempts": _MFA_CHALLENGE_MAX_ATTEMPTS},
            )
            raise InvalidTokenError("MFA challenge locked after too many failed attempts")

        if not await self._consume_mfa_code(user, code):
            await self._audit(
                event_type="auth.mfa.login_failed",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                context={},
            )
            raise InvalidMfaCodeError("Invalid MFA code")

        # Single-use: burn the challenge the instant it's successfully
        # redeemed, regardless of how much of its own TTL is left.
        remaining_seconds = max(int((claims.expires_at - datetime.now(UTC)).total_seconds()), 1)
        await self._token_blacklist.add_jti(challenge_key, ttl_seconds=remaining_seconds)

        organization: Organization | None = None
        role: Role | None = None
        if claims.organization_id is not None:
            organization = await self._orgs.get_by_id(claims.organization_id)
            if organization is not None:
                membership = await self._orgs.get_membership(claims.organization_id, user.id)
                # Membership may have been revoked since the challenge was
                # issued — drop tenant context silently rather than fail a
                # password+MFA-correct login over a stale claim.
                organization = organization if membership is not None else None
                role = membership.role if membership is not None else None

        previous_last_login_at = user.last_login_at
        user.last_login_at = datetime.now(UTC)

        token_pair = await self.issue_new_session(
            user,
            ip_address=ip_address,
            user_agent=user_agent,
            organization=organization,
            role=role,
        )
        await self._audit(
            event_type="auth.login.success",
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            context={"mfa": True},
        )
        return LoginResult(
            user=user,
            mfa_required=False,
            access_token=token_pair.access_token,
            refresh_token=token_pair.refresh_token,
            organization=organization,
            role=role,
            permissions=sorted(p.code for p in role.permissions) if role else [],
            session_id=token_pair.session_id,
            session_issued_at=token_pair.issued_at,
            session_expires_at=token_pair.expires_at,
            previous_last_login_at=previous_last_login_at,
        )

    async def _consume_mfa_code(self, user: User, code: str) -> bool:
        """Tries the code as a live TOTP code first, then as a one-time
        recovery code (consuming it on success)."""
        assert user.mfa_secret_encrypted is not None
        secret = decrypt_secret(self._settings, user.mfa_secret_encrypted)
        if verify_totp_code(secret, code):
            return True

        code_hash = hash_recovery_code(code)
        if code_hash in user.mfa_recovery_codes:
            user.mfa_recovery_codes = [stored for stored in user.mfa_recovery_codes if stored != code_hash]
            user.updated_at = datetime.now(UTC)
            return True

        return False

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
        """Re-mints the caller's access token under a *different* tenant
        they already have an active membership in — no re-authentication.

        Best-effort rotates ``current_refresh_token`` (if it's still a live,
        unrevoked token belonging to this user) into the new tenant context
        too, via the same rotation machinery as a normal /refresh — without
        this, a later silent token refresh would re-resolve the *old*
        ``stored.organization_id`` and silently revert the switch. A caller
        with no usable refresh token on hand still succeeds with a
        standalone access token; there's just nothing to carry forward.
        """
        organization = await self._orgs.get_by_slug(tenant_slug)
        if organization is None:
            raise OrganizationNotFoundError(f"No tenant '{tenant_slug}'")

        membership = await self._orgs.get_membership(organization.id, user.id)
        if membership is None or not membership.is_active:
            raise ForbiddenError("You are not an active member of this tenant")

        stored: RefreshToken | None = None
        if current_refresh_token is not None:
            try:
                refresh_claims = decode_refresh_token(self._settings, current_refresh_token)
            except InvalidTokenError:
                refresh_claims = None
            if refresh_claims is not None and refresh_claims.subject_id == user.id:
                candidate = await self._refresh_tokens.get_by_id(refresh_claims.jti)
                if candidate is not None and candidate.revoked_at is None:
                    stored = candidate

        if stored is not None:
            token_pair = await self._issue_token_pair(
                user,
                family_id=stored.family_id,
                ip_address=ip_address,
                user_agent=user_agent,
                rotates=stored,
                organization=organization,
                role=membership.role,
            )
            access_token = token_pair.access_token
            refresh_token_out: str | None = token_pair.refresh_token
        else:
            access_token = create_access_token(
                self._settings,
                user_id=user.id,
                attributes=user.attributes,
                tenant_id=organization.slug,
                role=membership.role.name,
            )
            refresh_token_out = None

        await self._audit(
            event_type="auth.tenant_switched",
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            context={"organization_id": str(organization.id)},
        )
        return SwitchTenantResult(
            access_token=access_token,
            refresh_token=refresh_token_out,
            organization=organization,
            role=membership.role,
        )

    # -- MFA enrollment ---------------------------------------------------

    async def setup_mfa(self, *, user_id: uuid.UUID) -> tuple[str, str]:
        """Starts (or restarts) enrollment: generates a fresh secret and
        returns ``(secret, otpauth_uri)``. Not active until ``confirm_mfa``
        verifies a code against it — calling this again before confirming
        just replaces the pending secret."""
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(f"No user with id '{user_id}'")
        if user.mfa_enabled:
            raise MfaAlreadyEnabledError("MFA is already enabled for this account")

        secret = generate_totp_secret()
        user.mfa_secret_encrypted = encrypt_secret(self._settings, secret)
        user.updated_at = datetime.now(UTC)
        await self._audit(event_type="auth.mfa.setup_started", user_id=user.id, context={})
        return secret, build_otpauth_uri(secret=secret, account_email=user.email)

    async def confirm_mfa(self, *, user_id: uuid.UUID, code: str) -> list[str]:
        """Verifies a code against the pending secret from ``setup_mfa``,
        enables MFA, and returns a fresh batch of raw recovery codes —
        shown to the caller exactly once; only their hashes are persisted."""
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(f"No user with id '{user_id}'")
        if user.mfa_enabled:
            raise MfaAlreadyEnabledError("MFA is already enabled for this account")
        if user.mfa_secret_encrypted is None:
            raise MfaNotEnabledError("Call POST /auth/mfa/setup before confirming")

        secret = decrypt_secret(self._settings, user.mfa_secret_encrypted)
        if not verify_totp_code(secret, code):
            raise InvalidMfaCodeError("Invalid MFA code")

        recovery_codes = generate_recovery_codes(self._settings.mfa_recovery_code_count)
        user.mfa_enabled = True
        user.mfa_recovery_codes = [hash_recovery_code(c) for c in recovery_codes]
        user.updated_at = datetime.now(UTC)
        await self._audit(event_type="auth.mfa.enabled", user_id=user.id, context={})
        return recovery_codes

    async def disable_mfa(self, *, user_id: uuid.UUID, current_password: str, code: str) -> None:
        """Disabling lowers account security, so it's gated the same way as
        a password change: the current password *and* a live MFA code."""
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(f"No user with id '{user_id}'")
        if not user.mfa_enabled:
            raise MfaNotEnabledError("MFA is not enabled for this account")
        if user.password_hash is None or not verify_password(current_password, user.password_hash):
            raise InvalidCredentialsError("Invalid password")
        if not await self._consume_mfa_code(user, code):
            raise InvalidMfaCodeError("Invalid MFA code")

        user.mfa_enabled = False
        user.mfa_secret_encrypted = None
        user.mfa_recovery_codes = []
        user.updated_at = datetime.now(UTC)
        await self._audit(event_type="auth.mfa.disabled", user_id=user.id, context={})

    async def _record_failed_login(
        self, user: User, *, ip_address: str | None, user_agent: str | None
    ) -> None:
        user.failed_login_count += 1
        settings = self._settings

        if user.failed_login_count >= settings.lockout_max_attempts:
            backoff_steps = user.failed_login_count - settings.lockout_max_attempts
            lock_seconds = min(
                settings.lockout_base_seconds * (2**backoff_steps),
                settings.lockout_max_seconds,
            )
            user.locked_until = datetime.now(UTC) + timedelta(seconds=lock_seconds)
            # Keep User.status (PATCH /users/{id}/status) in sync with the
            # brute-force lockout — see UserService.set_status.
            user.status = "LOCKED"
            await self._audit(
                event_type="auth.login.locked",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                context={"lock_seconds": lock_seconds},
            )
        else:
            await self._audit(
                event_type="auth.login.failure",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                context={"failed_login_count": user.failed_login_count},
            )

    async def issue_new_session(
        self,
        user: User,
        *,
        ip_address: str | None,
        user_agent: str | None,
        organization: Organization | None = None,
        role: Role | None = None,
    ) -> TokenPair:
        """Start a brand-new rotation family — used by password login, the
        post-MFA verify step, and the Google OIDC callback once an identity
        has been resolved to a user. ``organization``/``role`` are omitted
        by the Google flow today (it has no tenant-resolution step yet)."""
        return await self._issue_token_pair(
            user,
            family_id=uuid.uuid4(),
            ip_address=ip_address,
            user_agent=user_agent,
            organization=organization,
            role=role,
        )

    # -- refresh token rotation ---------------------------------------------

    async def refresh(
        self, *, refresh_token: str, ip_address: str | None, user_agent: str | None
    ) -> TokenPair:
        claims = decode_refresh_token(self._settings, refresh_token)
        stored = await self._refresh_tokens.get_by_id(claims.jti)

        if stored is None:
            raise InvalidTokenError("Unknown refresh token")

        if stored.revoked_at is not None:
            await self._refresh_tokens.revoke_family(stored.family_id)
            await self._audit(
                event_type="auth.refresh.reuse_detected",
                user_id=stored.user_id,
                ip_address=ip_address,
                user_agent=user_agent,
                context={"family_id": str(stored.family_id)},
            )
            raise RefreshTokenReusedError("Refresh token has already been used")

        if _aware(stored.expires_at) < datetime.now(UTC):
            raise InvalidTokenError("Refresh token has expired")

        user = await self._session.get(User, stored.user_id)
        if user is None or not user.is_active:
            raise UserNotFoundError("Refresh token's user is no longer valid")

        # Re-resolve the tenant fresh from the DB on every rotation (see
        # migration 0010) rather than trusting the prior access token's
        # tenant_id/role claims — keeps them from going stale if role/
        # membership changed since the last rotation. Membership having been
        # revoked since just drops tenant context, same as in
        # verify_mfa_and_login, rather than failing the refresh outright.
        organization: Organization | None = None
        role: Role | None = None
        if stored.organization_id is not None:
            organization = await self._orgs.get_by_id(stored.organization_id)
            if organization is not None:
                membership = await self._orgs.get_membership(stored.organization_id, user.id)
                organization = organization if membership is not None else None
                role = membership.role if membership is not None else None

        token_pair = await self._issue_token_pair(
            user,
            family_id=stored.family_id,
            ip_address=ip_address,
            user_agent=user_agent,
            rotates=stored,
            organization=organization,
            role=role,
        )
        await self._audit(
            event_type="auth.refresh.rotated",
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            context={"family_id": str(stored.family_id)},
        )
        return token_pair

    async def _issue_token_pair(
        self,
        user: User,
        *,
        family_id: uuid.UUID,
        ip_address: str | None,
        user_agent: str | None,
        rotates: RefreshToken | None = None,
        organization: Organization | None = None,
        role: Role | None = None,
    ) -> TokenPair:
        new_jti = uuid.uuid4()
        issued_at = datetime.now(UTC)
        expires_at = issued_at + timedelta(days=self._settings.refresh_token_expire_days)

        new_row = RefreshToken(
            id=new_jti,
            user_id=user.id,
            family_id=family_id,
            issued_at=issued_at,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
            organization_id=organization.id if organization else None,
        )
        self._refresh_tokens.add(new_row)
        # Flush the INSERT before the UPDATE below: replaced_by_jti is a
        # self-referential FK on this same table, and SQLAlchemy's unit-of-
        # work only topologically sorts same-flush operations using declared
        # relationships, not raw FK columns — so in one flush it can (and on
        # Postgres, did) emit the UPDATE before the new row's INSERT,
        # violating fk_refresh_tokens_replaced_by_jti_refresh_tokens.
        await self._session.flush()

        if rotates is not None:
            rotates.revoked_at = datetime.now(UTC)
            rotates.replaced_by_jti = new_jti
            await self._session.flush()

        access_token = create_access_token(
            self._settings,
            user_id=user.id,
            attributes=user.attributes,
            tenant_id=organization.slug if organization else None,
            role=role.name if role else None,
        )
        access_expires_at = issued_at + timedelta(minutes=self._settings.access_token_expire_minutes)
        refresh_token_str = create_refresh_token(
            self._settings,
            user_id=user.id,
            jti=new_jti,
            family_id=family_id,
            expires_at=expires_at,
        )
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token_str,
            session_id=new_jti,
            issued_at=issued_at,
            expires_at=access_expires_at,
        )

    # -- logout --------------------------------------------------------------

    async def logout(self, *, refresh_token: str | None, access_token: str | None) -> None:
        if refresh_token:
            try:
                claims = decode_refresh_token(self._settings, refresh_token)
            except InvalidTokenError:
                claims = None
            if claims is not None:
                await self._refresh_tokens.revoke_family(claims.family_id)
                await self._audit(event_type="auth.logout", user_id=claims.subject_id, context={})

        if access_token:
            try:
                access_claims = decode_access_token(self._settings, access_token)
            except InvalidTokenError:
                access_claims = None
            if access_claims is not None:
                ttl_seconds = max(
                    int((access_claims.expires_at - datetime.now(UTC)).total_seconds()),
                    1,
                )
                await self._token_blacklist.add_jti(str(access_claims.jti), ttl_seconds=ttl_seconds)

    # -- session management -----------------------------------------------

    async def list_sessions(self, user_id: uuid.UUID) -> list[RefreshToken]:
        """Each row in `refresh_tokens` *is* a session record (see
        RefreshToken) — active means not revoked and not yet expired."""
        tokens = await self._refresh_tokens.list_active_for_user(user_id)
        now = datetime.now(UTC)
        return [token for token in tokens if _aware(token.expires_at) > now]

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
            or _aware(token.expires_at) <= datetime.now(UTC)
        ):
            raise SessionNotFoundError(f"No active session '{session_id}' for this user")
        token.revoked_at = datetime.now(UTC)
        await self._audit(event_type="auth.session.revoked", user_id=user_id, context={})
        await self._session.commit()

    # -- password management ---------------------------------------------------

    async def change_password(self, *, user_id: uuid.UUID, current_password: str, new_password: str) -> None:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(f"No user with id '{user_id}'")
        if user.password_hash is None or not verify_password(current_password, user.password_hash):
            raise InvalidCredentialsError("Current password is incorrect")

        now = datetime.now(UTC)
        user.password_hash = hash_password(new_password)
        user.password_changed_at = now
        user.updated_at = now
        user.must_change_password = False

        # A credential change invalidates every session started under the
        # old credential — not just the one making this request. Refresh
        # tokens are revoked directly; already-issued *access* tokens are
        # still cryptographically valid until they expire, so they're killed
        # via invalidate_before instead (no jti to target individually).
        await self._refresh_tokens.revoke_all_for_user(user_id)
        await self._invalidate_access_tokens_issued_before(user_id, now)
        await self._audit(event_type="auth.password.changed", user_id=user_id, context={})

    async def request_password_reset(self, *, email: str) -> str | None:
        """Returns the raw reset token only when `settings.debug` is set —
        there is no email/notification service in this $0 stack, so dev/test
        environments get the token back directly instead of via a delivered
        email. Always returns the same shape (None in production, where a
        real delivery channel would exist) regardless of whether `email`
        matched an account, so this never reveals account existence.
        """
        normalized_email = Email(email).value
        user = await self._users.get_by_email(normalized_email)
        if user is None:
            return None

        raw_token, token_hash = generate_reset_token()
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=self._settings.password_reset_token_expire_minutes)
        self._reset_tokens.add(
            PasswordResetToken(
                token_hash=token_hash,
                user_id=user.id,
                expires_at=expires_at,
                created_at=now,
            )
        )
        await self._session.flush()
        await self._audit(event_type="auth.password.reset_requested", user_id=user.id, context={})

        return raw_token if self._settings.debug else None

    async def reset_password(self, *, raw_token: str, new_password: str) -> None:
        token_row = await self._reset_tokens.get_by_token_hash(hash_reset_token(raw_token))

        if (
            token_row is None
            or token_row.used_at is not None
            or _aware(token_row.expires_at) < datetime.now(UTC)
        ):
            # Same message for "no such token", "already used", and
            # "expired" — don't help an attacker narrow down which.
            raise InvalidTokenError("Invalid or expired password reset token")

        user = await self._users.get_by_id(token_row.user_id)
        if user is None:
            raise InvalidTokenError("Invalid or expired password reset token")

        now = datetime.now(UTC)
        user.password_hash = hash_password(new_password)
        user.password_changed_at = now
        user.updated_at = now
        user.must_change_password = False
        token_row.used_at = now

        await self._refresh_tokens.revoke_all_for_user(user.id)
        await self._invalidate_access_tokens_issued_before(user.id, now)
        await self._audit(event_type="auth.password.reset_completed", user_id=user.id, context={})

    async def _invalidate_access_tokens_issued_before(self, user_id: uuid.UUID, when: datetime) -> None:
        # NOTE: JWT `iat` is always encoded/decoded as an integer unix
        # timestamp, so a token issued in the *same wall-clock second* as
        # this call is ambiguous (its floored iat can't be ordered against
        # this precise timestamp). That's resolved in favor of security: an
        # old, stale token from that same second stays rejected rather than
        # risk it staying valid — a brand-new token minted in that same
        # second just has to be requested again a moment later, which is a
        # safe failure mode.
        ttl_seconds = self._settings.access_token_expire_minutes * 60
        await self._token_blacklist.set_invalidate_before(
            str(user_id), timestamp=when.timestamp(), ttl_seconds=ttl_seconds
        )

    # -- shared helpers --------------------------------------------------------

    async def _audit(
        self,
        *,
        event_type: str,
        user_id: uuid.UUID | None,
        context: dict,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        self._audit_log.add(
            AuditLog(
                id=uuid.uuid4(),
                user_id=user_id,
                event_type=event_type,
                ip_address=ip_address,
                user_agent=user_agent,
                context=context,
                created_at=datetime.now(UTC),
            )
        )
        # Commit, not flush: every audit call here is the last write of either
        # a success path or a "reject this request" path (lockout, reuse
        # detection). On the reject paths the caller raises a DomainError
        # right after this, and the request-scoped session dependency rolls
        # back on any exception — without an explicit commit here, the audit
        # row (and e.g. the failed_login_count bump) would vanish along with
        # the exception instead of surviving it.
        await self._session.commit()
