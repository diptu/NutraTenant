from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.audit import AuditLogRepository
from app.core.config import Settings
from app.core.rate_limit import RateLimiter
from app.infrastructure.database.associations import UserOrganizationRole
from app.modules.auth.exceptions import (
    AccountLockedError,
    InvalidCredentialsError,
    RateLimitExceededError,
    TenantSelectionRequiredError,
)
from app.modules.auth.repositories.interfaces.token_repository import RefreshTokenRepository
from app.modules.auth.schemas.commands.login_command import LoginCommand
from app.modules.auth.schemas.dto.login_result_dto import LoginResult
from app.modules.auth.use_cases._audit import record_auth_audit_event
from app.modules.auth.use_cases._dates import aware
from app.modules.auth.use_cases._session import issue_new_session
from app.modules.auth.utils.jwt import create_mfa_challenge_token
from app.modules.auth.utils.passwords import verify_password
from app.modules.organizations.models import Organization
from app.modules.organizations.repositories.interfaces.organization_repository import (
    OrganizationRepository,
)
from app.modules.users.models import User
from app.modules.users.repositories.interfaces.user_repository import UserRepository
from app.shared.exceptions.base import ForbiddenError
from app.shared.value_objects import Email
from sqlalchemy.ext.asyncio import AsyncSession


class LoginUseCase:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        rate_limiter: RateLimiter,
        users: UserRepository,
        orgs: OrganizationRepository,
        refresh_tokens: RefreshTokenRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._session = session
        self._settings = settings
        self._rate_limiter = rate_limiter
        self._users = users
        self._orgs = orgs
        self._refresh_tokens = refresh_tokens
        self._audit_log = audit_log

    async def execute(self, command: LoginCommand) -> LoginResult:
        normalized_email = Email(command.email).value

        # Per-email, not global — one attacker hammering one account can't
        # lock everyone else out of attempting their own (correct) login.
        rate_limit = await self._rate_limiter.hit(
            f"login:{normalized_email}",
            limit=self._settings.rate_limit_max_requests,
            window_seconds=self._settings.rate_limit_window_seconds,
        )
        if not rate_limit.allowed:
            await record_auth_audit_event(
                self._session,
                self._audit_log,
                "auth.login.rate_limited",
                None,
                {"email": normalized_email},
                ip_address=command.ip_address,
                user_agent=command.user_agent,
            )
            raise RateLimitExceededError(retry_after_seconds=rate_limit.retry_after_seconds)

        user = await self._users.get_by_email(normalized_email)

        if user is None or user.password_hash is None:
            # Same error for "no such user" and "OAuth-only account" — don't
            # let a login attempt enumerate which accounts exist or how
            # they authenticate.
            raise InvalidCredentialsError("Invalid email or password")

        if user.locked_until is not None and aware(user.locked_until) > datetime.now(UTC):
            retry_after = int((aware(user.locked_until) - datetime.now(UTC)).total_seconds())
            raise AccountLockedError(retry_after_seconds=max(retry_after, 1))

        if not verify_password(command.password, user.password_hash):
            await self._record_failed_login(
                user, ip_address=command.ip_address, user_agent=command.user_agent
            )
            raise InvalidCredentialsError("Invalid email or password")

        # Resolved (and any TenantSelectionRequiredError/ForbiddenError
        # raised) before mutating any user state below — the request-scoped
        # session rolls back on the exception either way, but this keeps
        # "did this attempt even get past tenant resolution" unambiguous.
        organization, membership = await self._resolve_tenant(user.id, command.tenant_id)

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
            await record_auth_audit_event(
                self._session,
                self._audit_log,
                "auth.login.mfa_challenge_issued",
                user.id,
                {},
                ip_address=command.ip_address,
                user_agent=command.user_agent,
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
        token_pair = await issue_new_session(
            self._session,
            self._settings,
            self._refresh_tokens,
            user,
            ip_address=command.ip_address,
            user_agent=command.user_agent,
            organization=organization,
        )
        await record_auth_audit_event(
            self._session,
            self._audit_log,
            "auth.login.success",
            user.id,
            {"organization_id": str(organization.id) if organization else None},
            ip_address=command.ip_address,
            user_agent=command.user_agent,
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
            await record_auth_audit_event(
                self._session,
                self._audit_log,
                "auth.login.locked",
                user.id,
                {"lock_seconds": lock_seconds},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        else:
            await record_auth_audit_event(
                self._session,
                self._audit_log,
                "auth.login.failure",
                user.id,
                {"failed_login_count": user.failed_login_count},
                ip_address=ip_address,
                user_agent=user_agent,
            )
