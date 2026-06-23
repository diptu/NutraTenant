from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.audit import AuditLogRepository
from app.core.config import Settings
from app.modules.auth.models import PasswordResetToken
from app.modules.auth.repositories.interfaces.token_repository import (
    PasswordResetTokenRepository,
)
from app.modules.auth.schemas.commands.request_password_reset_command import (
    RequestPasswordResetCommand,
)
from app.modules.auth.use_cases._audit import record_auth_audit_event
from app.modules.auth.utils.tokens import generate_reset_token
from app.modules.users.repositories.interfaces.user_repository import UserRepository
from app.shared.value_objects import Email
from sqlalchemy.ext.asyncio import AsyncSession


class RequestPasswordResetUseCase:
    """Returns the raw reset token only when `settings.debug` is set —
    there is no email/notification service in this $0 stack, so dev/test
    environments get the token back directly instead of via a delivered
    email. Always returns the same shape (None in production, where a
    real delivery channel would exist) regardless of whether `email`
    matched an account, so this never reveals account existence.
    """

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        users: UserRepository,
        reset_tokens: PasswordResetTokenRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._session = session
        self._settings = settings
        self._users = users
        self._reset_tokens = reset_tokens
        self._audit_log = audit_log

    async def execute(self, command: RequestPasswordResetCommand) -> str | None:
        normalized_email = Email(command.email).value
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
        await record_auth_audit_event(
            self._session, self._audit_log, "auth.password.reset_requested", user.id, {}
        )

        return raw_token if self._settings.debug else None
