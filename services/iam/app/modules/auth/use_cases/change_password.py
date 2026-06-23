from __future__ import annotations

from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.core.config import Settings
from app.core.token_blacklist import TokenBlacklist
from app.modules.auth.exceptions import InvalidCredentialsError
from app.modules.auth.repositories.interfaces.token_repository import RefreshTokenRepository
from app.modules.auth.schemas.commands.change_password_command import ChangePasswordCommand
from app.modules.auth.use_cases._audit import record_auth_audit_event
from app.modules.auth.use_cases._invalidate import invalidate_access_tokens_issued_before
from app.modules.auth.utils.passwords import hash_password, verify_password
from app.modules.users.exceptions import UserNotFoundError
from app.modules.users.repositories.interfaces.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession


class ChangePasswordUseCase:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        token_blacklist: TokenBlacklist,
        users: UserRepository,
        refresh_tokens: RefreshTokenRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._session = session
        self._settings = settings
        self._token_blacklist = token_blacklist
        self._users = users
        self._refresh_tokens = refresh_tokens
        self._audit_log = audit_log

    async def execute(self, command: ChangePasswordCommand) -> None:
        user = await self._users.get_by_id(command.user_id)
        if user is None:
            raise UserNotFoundError(f"No user with id '{command.user_id}'")
        if user.password_hash is None or not verify_password(command.current_password, user.password_hash):
            raise InvalidCredentialsError("Current password is incorrect")

        now = datetime.now(UTC)
        user.password_hash = hash_password(command.new_password)
        user.password_changed_at = now
        user.updated_at = now
        user.must_change_password = False

        # A credential change invalidates every session started under the
        # old credential — not just the one making this request. Refresh
        # tokens are revoked directly; already-issued *access* tokens are
        # still cryptographically valid until they expire, so they're killed
        # via invalidate_before instead (no jti to target individually).
        await self._refresh_tokens.revoke_all_for_user(command.user_id)
        await invalidate_access_tokens_issued_before(
            self._token_blacklist, self._settings, command.user_id, now
        )
        await record_auth_audit_event(
            self._session, self._audit_log, "auth.password.changed", command.user_id, {}
        )
