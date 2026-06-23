from __future__ import annotations

from app.audit import AuditLogRepository
from app.modules.users.repositories.interfaces.user_repository import UserRepository
from app.modules.users.schemas.commands.delete_user_command import DeleteUserCommand
from app.modules.users.use_cases._audit import record_user_audit_event
from app.modules.users.use_cases._lookups import get_user
from sqlalchemy.ext.asyncio import AsyncSession


class DeleteUserUseCase:
    def __init__(self, session: AsyncSession, users: UserRepository, audit_log: AuditLogRepository) -> None:
        self._session = session
        self._users = users
        self._audit_log = audit_log

    async def execute(self, command: DeleteUserCommand) -> None:
        user = await get_user(self._users, command.user_id)
        await self._users.delete(user)
        await self._session.flush()
        await record_user_audit_event(
            self._session,
            self._audit_log,
            "user.deleted",
            command.actor_id,
            {"user_id": str(command.user_id)},
        )
