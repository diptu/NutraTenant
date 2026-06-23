from __future__ import annotations

from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.core.config import Settings
from app.core.token_blacklist import TokenBlacklist
from app.modules.auth.exceptions import InvalidTokenError
from app.modules.auth.repositories.interfaces.token_repository import (
    PasswordResetTokenRepository,
    RefreshTokenRepository,
)
from app.modules.auth.schemas.commands.reset_password_command import ResetPasswordCommand
from app.modules.auth.use_cases._audit import record_auth_audit_event
from app.modules.auth.use_cases._dates import aware
from app.modules.auth.use_cases._invalidate import invalidate_access_tokens_issued_before
from app.modules.auth.utils.passwords import hash_password
from app.modules.auth.utils.tokens import hash_reset_token
from app.modules.users.repositories.interfaces.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession


class ResetPasswordUseCase:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        token_blacklist: TokenBlacklist,
        users: UserRepository,
        reset_tokens: PasswordResetTokenRepository,
        refresh_tokens: RefreshTokenRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._session = session
        self._settings = settings
        self._token_blacklist = token_blacklist
        self._users = users
        self._reset_tokens = reset_tokens
        self._refresh_tokens = refresh_tokens
        self._audit_log = audit_log

    async def execute(self, command: ResetPasswordCommand) -> None:
        token_row = await self._reset_tokens.get_by_token_hash(hash_reset_token(command.raw_token))

        if (
            token_row is None
            or token_row.used_at is not None
            or aware(token_row.expires_at) < datetime.now(UTC)
        ):
            # Same message for "no such token", "already used", and
            # "expired" — don't help an attacker narrow down which.
            raise InvalidTokenError("Invalid or expired password reset token")

        user = await self._users.get_by_id(token_row.user_id)
        if user is None:
            raise InvalidTokenError("Invalid or expired password reset token")

        now = datetime.now(UTC)
        user.password_hash = hash_password(command.new_password)
        user.password_changed_at = now
        user.updated_at = now
        user.must_change_password = False
        token_row.used_at = now

        await self._refresh_tokens.revoke_all_for_user(user.id)
        await invalidate_access_tokens_issued_before(self._token_blacklist, self._settings, user.id, now)
        await record_auth_audit_event(
            self._session, self._audit_log, "auth.password.reset_completed", user.id, {}
        )
