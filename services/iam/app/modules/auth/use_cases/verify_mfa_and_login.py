from __future__ import annotations

from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.core.config import Settings
from app.core.rate_limit import RateLimiter
from app.core.token_blacklist import TokenBlacklist
from app.modules.auth.exceptions import (
    InvalidMfaCodeError,
    InvalidTokenError,
    RateLimitExceededError,
)
from app.modules.auth.repositories.interfaces.token_repository import RefreshTokenRepository
from app.modules.auth.schemas.commands.verify_mfa_and_login_command import (
    VerifyMfaAndLoginCommand,
)
from app.modules.auth.schemas.dto.login_result_dto import LoginResult
from app.modules.auth.use_cases._audit import record_auth_audit_event
from app.modules.auth.use_cases._mfa import consume_mfa_code
from app.modules.auth.use_cases._session import issue_new_session
from app.modules.auth.utils.jwt import decode_mfa_challenge_token
from app.modules.organizations.models import Organization
from app.modules.organizations.repositories.interfaces.organization_repository import (
    OrganizationRepository,
)
from app.modules.roles.models import Role
from app.modules.users.repositories.interfaces.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession

# Per-challenge-token cap on OTP attempts (distinct from the per-account
# `mfa-verify:{user.id}` limiter).
_MFA_CHALLENGE_MAX_ATTEMPTS = 3


def _mfa_challenge_blacklist_key(jti) -> str:
    """Namespaced so a challenge token's jti can never collide with an
    access token's jti in the shared TokenBlacklist keyspace."""
    return f"mfa-challenge:{jti}"


class VerifyMfaAndLoginUseCase:
    """Redeems an MFA challenge token (from ``LoginUseCase``) plus a TOTP/
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

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        token_blacklist: TokenBlacklist,
        rate_limiter: RateLimiter,
        users: UserRepository,
        orgs: OrganizationRepository,
        refresh_tokens: RefreshTokenRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._session = session
        self._settings = settings
        self._token_blacklist = token_blacklist
        self._rate_limiter = rate_limiter
        self._users = users
        self._orgs = orgs
        self._refresh_tokens = refresh_tokens
        self._audit_log = audit_log

    async def execute(self, command: VerifyMfaAndLoginCommand) -> LoginResult:
        claims = decode_mfa_challenge_token(self._settings, command.mfa_challenge_token)

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
            await record_auth_audit_event(
                self._session,
                self._audit_log,
                "auth.mfa.challenge_locked",
                user.id,
                {"max_attempts": _MFA_CHALLENGE_MAX_ATTEMPTS},
                ip_address=command.ip_address,
                user_agent=command.user_agent,
            )
            raise InvalidTokenError("MFA challenge locked after too many failed attempts")

        if not await consume_mfa_code(self._settings, user, command.code):
            await record_auth_audit_event(
                self._session,
                self._audit_log,
                "auth.mfa.login_failed",
                user.id,
                {},
                ip_address=command.ip_address,
                user_agent=command.user_agent,
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
            {"mfa": True},
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
