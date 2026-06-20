"""Registration, password login, refresh-token rotation, and logout.

Orchestration only — persistence goes through the repository layer, token
mechanics through app.infrastructure.security.jwt, hashing through
app.infrastructure.security.password. The caller (a FastAPI dependency,
or a test) owns the session's commit/rollback boundary; this service only
flushes when it needs a DB-assigned default or a constraint violation to
surface before deciding what to do next.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.rate_limit import RateLimiter
from app.core.token_blacklist import TokenBlacklist
from app.domain.exceptions import (
    AccountLockedError,
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    InvalidTokenError,
    RateLimitExceededError,
    RefreshTokenReusedError,
    UserNotFoundError,
)
from app.domain.value_objects import Email
from app.infrastructure.db.models.audit_log import AuditLog
from app.infrastructure.db.models.password_reset_token import PasswordResetToken
from app.infrastructure.db.models.refresh_token import RefreshToken
from app.infrastructure.db.models.user import User
from app.infrastructure.db.repositories.audit_repo import AuditLogRepository
from app.infrastructure.db.repositories.password_reset_token_repo import (
    PasswordResetTokenRepository,
)
from app.infrastructure.db.repositories.refresh_token_repo import RefreshTokenRepository
from app.infrastructure.db.repositories.user_repo import UserRepository
from app.infrastructure.security.jwt import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
)
from app.infrastructure.security.password import hash_password, verify_password
from app.infrastructure.security.reset_token import (
    generate_reset_token,
    hash_reset_token,
)


def _aware(value: datetime) -> datetime:
    """Postgres' ``DateTime(timezone=True)`` round-trips tz-aware; SQLite (tests
    only) round-trips naive. Normalize before comparing against `datetime.now(UTC)`."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


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

    # -- registration ----------------------------------------------------

    async def register(
        self, *, email: str, password: str, full_name: str | None
    ) -> User:
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
            raise EmailAlreadyExistsError(
                f"'{normalized_email}' is already registered"
            ) from exc

        await self._audit(event_type="user.registered", user_id=user.id, context={})
        return user

    # -- password login ----------------------------------------------------

    async def login(
        self,
        *,
        email: str,
        password: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> tuple[str, str, User]:
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
            raise RateLimitExceededError(
                retry_after_seconds=rate_limit.retry_after_seconds
            )

        user = await self._users.get_by_email(normalized_email)

        if user is None or user.password_hash is None:
            # Same error for "no such user" and "OAuth-only account" — don't
            # let a login attempt enumerate which accounts exist or how
            # they authenticate.
            raise InvalidCredentialsError("Invalid email or password")

        if user.locked_until is not None and _aware(user.locked_until) > datetime.now(
            UTC
        ):
            retry_after = int(
                (_aware(user.locked_until) - datetime.now(UTC)).total_seconds()
            )
            raise AccountLockedError(retry_after_seconds=max(retry_after, 1))

        if not verify_password(password, user.password_hash):
            await self._record_failed_login(
                user, ip_address=ip_address, user_agent=user_agent
            )
            raise InvalidCredentialsError("Invalid email or password")

        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = datetime.now(UTC)
        user.updated_at = datetime.now(UTC)

        access_token, refresh_token = await self.issue_new_session(
            user, ip_address=ip_address, user_agent=user_agent
        )
        await self._audit(
            event_type="auth.login.success",
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            context={},
        )
        return access_token, refresh_token, user

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
        self, user: User, *, ip_address: str | None, user_agent: str | None
    ) -> tuple[str, str]:
        """Start a brand-new rotation family — used by password login and by
        the Google OIDC callback once an identity has been resolved to a user."""
        return await self._issue_token_pair(
            user, family_id=uuid.uuid4(), ip_address=ip_address, user_agent=user_agent
        )

    # -- refresh token rotation ---------------------------------------------

    async def refresh(
        self, *, refresh_token: str, ip_address: str | None, user_agent: str | None
    ) -> tuple[str, str]:
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

        access_token, refresh_token_str = await self._issue_token_pair(
            user,
            family_id=stored.family_id,
            ip_address=ip_address,
            user_agent=user_agent,
            rotates=stored,
        )
        await self._audit(
            event_type="auth.refresh.rotated",
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            context={"family_id": str(stored.family_id)},
        )
        return access_token, refresh_token_str

    async def _issue_token_pair(
        self,
        user: User,
        *,
        family_id: uuid.UUID,
        ip_address: str | None,
        user_agent: str | None,
        rotates: RefreshToken | None = None,
    ) -> tuple[str, str]:
        new_jti = uuid.uuid4()
        expires_at = datetime.now(UTC) + timedelta(
            days=self._settings.refresh_token_expire_days
        )

        new_row = RefreshToken(
            id=new_jti,
            user_id=user.id,
            family_id=family_id,
            issued_at=datetime.now(UTC),
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        self._refresh_tokens.add(new_row)

        if rotates is not None:
            rotates.revoked_at = datetime.now(UTC)
            rotates.replaced_by_jti = new_jti

        await self._session.flush()

        access_token = create_access_token(
            self._settings, user_id=user.id, attributes=user.attributes
        )
        refresh_token_str = create_refresh_token(
            self._settings,
            user_id=user.id,
            jti=new_jti,
            family_id=family_id,
            expires_at=expires_at,
        )
        return access_token, refresh_token_str

    # -- logout --------------------------------------------------------------

    async def logout(
        self, *, refresh_token: str | None, access_token: str | None
    ) -> None:
        if refresh_token:
            try:
                claims = decode_refresh_token(self._settings, refresh_token)
            except InvalidTokenError:
                claims = None
            if claims is not None:
                await self._refresh_tokens.revoke_family(claims.family_id)
                await self._audit(
                    event_type="auth.logout", user_id=claims.subject_id, context={}
                )

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
                await self._token_blacklist.add_jti(
                    str(access_claims.jti), ttl_seconds=ttl_seconds
                )

    # -- password management ---------------------------------------------------

    async def change_password(
        self, *, user_id: uuid.UUID, current_password: str, new_password: str
    ) -> None:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(f"No user with id '{user_id}'")
        if user.password_hash is None or not verify_password(
            current_password, user.password_hash
        ):
            raise InvalidCredentialsError("Current password is incorrect")

        now = datetime.now(UTC)
        user.password_hash = hash_password(new_password)
        user.password_changed_at = now
        user.updated_at = now

        # A credential change invalidates every session started under the
        # old credential — not just the one making this request. Refresh
        # tokens are revoked directly; already-issued *access* tokens are
        # still cryptographically valid until they expire, so they're killed
        # via invalidate_before instead (no jti to target individually).
        await self._refresh_tokens.revoke_all_for_user(user_id)
        await self._invalidate_access_tokens_issued_before(user_id, now)
        await self._audit(
            event_type="auth.password.changed", user_id=user_id, context={}
        )

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
        expires_at = now + timedelta(
            minutes=self._settings.password_reset_token_expire_minutes
        )
        self._reset_tokens.add(
            PasswordResetToken(
                token_hash=token_hash,
                user_id=user.id,
                expires_at=expires_at,
                created_at=now,
            )
        )
        await self._session.flush()
        await self._audit(
            event_type="auth.password.reset_requested", user_id=user.id, context={}
        )

        return raw_token if self._settings.debug else None

    async def reset_password(self, *, raw_token: str, new_password: str) -> None:
        token_row = await self._reset_tokens.get_by_token_hash(
            hash_reset_token(raw_token)
        )

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
        token_row.used_at = now

        await self._refresh_tokens.revoke_all_for_user(user.id)
        await self._invalidate_access_tokens_issued_before(user.id, now)
        await self._audit(
            event_type="auth.password.reset_completed", user_id=user.id, context={}
        )

    async def _invalidate_access_tokens_issued_before(
        self, user_id: uuid.UUID, when: datetime
    ) -> None:
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
