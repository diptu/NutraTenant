from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.audit import AuditLogRepository
from app.core.config import Settings
from app.infrastructure.notifications.email_sender import send_verification_email
from app.modules.auth.exceptions import EmailAlreadyExistsError
from app.modules.auth.models import EmailVerificationToken
from app.modules.auth.repositories.interfaces.token_repository import (
    EmailVerificationTokenRepository,
)
from app.modules.auth.schemas.commands.register_command import RegisterCommand
from app.modules.auth.use_cases._audit import record_auth_audit_event
from app.modules.auth.utils.passwords import hash_password
from app.modules.auth.utils.tokens import generate_verification_token
from app.modules.users.models import User
from app.modules.users.repositories.interfaces.user_repository import UserRepository
from app.shared.value_objects import Email
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class RegisterUseCase:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        users: UserRepository,
        verification_tokens: EmailVerificationTokenRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._session = session
        self._settings = settings
        self._users = users
        self._verification_tokens = verification_tokens
        self._audit_log = audit_log

    async def execute(self, command: RegisterCommand) -> tuple[User, str | None]:
        """Returns ``(user, verification_token)``. The raw verification
        token is only non-None when ``settings.debug`` is set — same
        debug-reveal convention as ``RequestPasswordResetUseCase`` (there's
        no email/notification provider wired up in this $0 stack)."""
        normalized_email = Email(command.email).value

        if await self._users.get_by_email(normalized_email) is not None:
            raise EmailAlreadyExistsError(f"'{normalized_email}' is already registered")

        now = datetime.now(UTC)
        user = User(
            id=uuid.uuid4(),
            email=normalized_email,
            full_name=command.full_name,
            password_hash=hash_password(command.password),
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

        raw_token, token_hash = generate_verification_token()
        expires_at = now + timedelta(minutes=self._settings.email_verification_token_expire_minutes)
        self._verification_tokens.add(
            EmailVerificationToken(
                token_hash=token_hash,
                user_id=user.id,
                expires_at=expires_at,
                created_at=now,
            )
        )
        await self._session.flush()
        await send_verification_email(to=normalized_email, verification_token=raw_token)

        await record_auth_audit_event(
            self._session, self._audit_log, "user.registered", user.id, {}
        )
        return user, (raw_token if self._settings.debug else None)
