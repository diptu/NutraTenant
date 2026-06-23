from __future__ import annotations

from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.users.models import User
from app.modules.users.repositories.interfaces.user_repository import UserRepository
from app.modules.users.schemas.commands.set_user_status_command import SetUserStatusCommand
from app.modules.users.use_cases._audit import record_user_audit_event
from app.modules.users.use_cases._lookups import get_user
from sqlalchemy.ext.asyncio import AsyncSession


class SetUserStatusUseCase:
    """PATCH /users/{user_id}/status — the one place that changes a
    user's lifecycle `status` and keeps `is_active`/`locked_until` in
    lockstep, so every existing access-gating check in this codebase
    (get_current_user, AuthService) keeps working unmodified off of
    `is_active` alone. Every non-ACTIVE status blocks access
    (`is_active=False`) — there's no "usable but pending" status today.
    """

    def __init__(self, session: AsyncSession, users: UserRepository, audit_log: AuditLogRepository) -> None:
        self._session = session
        self._users = users
        self._audit_log = audit_log

    async def execute(self, command: SetUserStatusCommand) -> User:
        user = await get_user(self._users, command.user_id)
        previous_status = user.status
        user.status = command.status
        user.is_active = command.status == "ACTIVE"
        if command.status != "LOCKED":
            user.locked_until = None
            user.failed_login_count = 0
        user.updated_at = datetime.now(UTC)
        await self._session.flush()
        await record_user_audit_event(
            self._session,
            self._audit_log,
            "user.status_changed",
            command.actor_id,
            {
                "user_id": str(command.user_id),
                "previous_status": previous_status,
                "new_status": command.status,
            },
        )
        return user
