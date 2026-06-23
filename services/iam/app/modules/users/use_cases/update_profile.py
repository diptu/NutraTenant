from __future__ import annotations

from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.auth.exceptions import UsernameAlreadyExistsError
from app.modules.users.models import User
from app.modules.users.repositories.interfaces.user_repository import UserRepository
from app.modules.users.schemas.commands.update_profile_command import UpdateProfileCommand
from app.modules.users.use_cases._audit import record_user_audit_event
from app.modules.users.use_cases._lookups import get_user
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class UpdateProfileUseCase:
    def __init__(self, session: AsyncSession, users: UserRepository, audit_log: AuditLogRepository) -> None:
        self._session = session
        self._users = users
        self._audit_log = audit_log

    async def execute(self, command: UpdateProfileCommand) -> User:
        user = await get_user(self._users, command.user_id)
        user.full_name = command.full_name
        user.username = command.username
        user.phone = command.phone
        user.avatar_url = command.avatar_url
        user.updated_at = datetime.now(UTC)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise UsernameAlreadyExistsError(f"Username '{command.username}' is already taken") from exc
        await record_user_audit_event(
            self._session,
            self._audit_log,
            "user.updated",
            command.actor_id,
            {"user_id": str(command.user_id)},
        )
        return user
