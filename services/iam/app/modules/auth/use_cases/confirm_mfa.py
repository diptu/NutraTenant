from __future__ import annotations

from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.core.config import Settings
from app.modules.auth.exceptions import (
    InvalidMfaCodeError,
    MfaAlreadyEnabledError,
    MfaNotEnabledError,
)
from app.modules.auth.schemas.commands.confirm_mfa_command import ConfirmMfaCommand
from app.modules.auth.use_cases._audit import record_auth_audit_event
from app.modules.auth.utils.mfa import (
    decrypt_secret,
    generate_recovery_codes,
    hash_recovery_code,
    verify_totp_code,
)
from app.modules.users.exceptions import UserNotFoundError
from app.modules.users.repositories.interfaces.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession


class ConfirmMfaUseCase:
    """Verifies a code against the pending secret from ``SetupMfaUseCase``,
    enables MFA, and returns a fresh batch of raw recovery codes —
    shown to the caller exactly once; only their hashes are persisted."""

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

    async def execute(self, command: ConfirmMfaCommand) -> list[str]:
        user = await self._users.get_by_id(command.user_id)
        if user is None:
            raise UserNotFoundError(f"No user with id '{command.user_id}'")
        if user.mfa_enabled:
            raise MfaAlreadyEnabledError("MFA is already enabled for this account")
        if user.mfa_secret_encrypted is None:
            raise MfaNotEnabledError("Call POST /auth/mfa/setup before confirming")

        secret = decrypt_secret(self._settings, user.mfa_secret_encrypted)
        if not verify_totp_code(secret, command.code):
            raise InvalidMfaCodeError("Invalid MFA code")

        recovery_codes = generate_recovery_codes(self._settings.mfa_recovery_code_count)
        user.mfa_enabled = True
        user.mfa_recovery_codes = [hash_recovery_code(c) for c in recovery_codes]
        user.updated_at = datetime.now(UTC)
        await record_auth_audit_event(self._session, self._audit_log, "auth.mfa.enabled", user.id, {})
        return recovery_codes
