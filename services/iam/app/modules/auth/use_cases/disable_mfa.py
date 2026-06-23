from __future__ import annotations

from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.core.config import Settings
from app.modules.auth.exceptions import InvalidCredentialsError, InvalidMfaCodeError, MfaNotEnabledError
from app.modules.auth.schemas.commands.disable_mfa_command import DisableMfaCommand
from app.modules.auth.use_cases._audit import record_auth_audit_event
from app.modules.auth.use_cases._mfa import consume_mfa_code
from app.modules.auth.utils.passwords import verify_password
from app.modules.users.exceptions import UserNotFoundError
from app.modules.users.repositories.interfaces.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession


class DisableMfaUseCase:
    """Disabling lowers account security, so it's gated the same way as
    a password change: the current password *and* a live MFA code."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        users: UserRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._session = session
        self._settings = settings
        self._users = users
        self._audit_log = audit_log

    async def execute(self, command: DisableMfaCommand) -> None:
        user = await self._users.get_by_id(command.user_id)
        if user is None:
            raise UserNotFoundError(f"No user with id '{command.user_id}'")
        if not user.mfa_enabled:
            raise MfaNotEnabledError("MFA is not enabled for this account")
        if user.password_hash is None or not verify_password(command.current_password, user.password_hash):
            raise InvalidCredentialsError("Invalid password")
        if not await consume_mfa_code(self._settings, user, command.code):
            raise InvalidMfaCodeError("Invalid MFA code")

        user.mfa_enabled = False
        user.mfa_secret_encrypted = None
        user.mfa_recovery_codes = []
        user.updated_at = datetime.now(UTC)
        await record_auth_audit_event(self._session, self._audit_log, "auth.mfa.disabled", user.id, {})
