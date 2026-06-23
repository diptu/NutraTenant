from __future__ import annotations

from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.core.config import Settings
from app.modules.auth.exceptions import MfaAlreadyEnabledError
from app.modules.auth.schemas.commands.setup_mfa_command import SetupMfaCommand
from app.modules.auth.use_cases._audit import record_auth_audit_event
from app.modules.auth.utils.mfa import build_otpauth_uri, encrypt_secret, generate_totp_secret
from app.modules.users.exceptions import UserNotFoundError
from app.modules.users.repositories.interfaces.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession


class SetupMfaUseCase:
    """Starts (or restarts) enrollment: generates a fresh secret and
    returns ``(secret, otpauth_uri)``. Not active until ``ConfirmMfaUseCase``
    verifies a code against it — calling this again before confirming
    just replaces the pending secret."""

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

    async def execute(self, command: SetupMfaCommand) -> tuple[str, str]:
        user = await self._users.get_by_id(command.user_id)
        if user is None:
            raise UserNotFoundError(f"No user with id '{command.user_id}'")
        if user.mfa_enabled:
            raise MfaAlreadyEnabledError("MFA is already enabled for this account")

        secret = generate_totp_secret()
        user.mfa_secret_encrypted = encrypt_secret(self._settings, secret)
        user.updated_at = datetime.now(UTC)
        await record_auth_audit_event(
            self._session, self._audit_log, "auth.mfa.setup_started", user.id, {}
        )
        return secret, build_otpauth_uri(secret=secret, account_email=user.email)
