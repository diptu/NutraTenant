from __future__ import annotations

from datetime import UTC, datetime

from app.modules.users.models import User
from app.modules.users.repositories.interfaces.user_repository import UserRepository
from app.modules.users.schemas.commands.update_profile_settings_command import (
    UpdateProfileSettingsCommand,
)
from app.modules.users.use_cases._lookups import get_user
from sqlalchemy.ext.asyncio import AsyncSession


class UpdateProfileSettingsUseCase:
    """PUT /api/v1/user-profiles/me — partial update (``None`` means
    "leave unchanged"), unlike :class:`UpdateProfileUseCase`'s full-replace
    semantics used by the pre-existing PATCH /users/{user_id}."""

    def __init__(self, session: AsyncSession, users: UserRepository) -> None:
        self._session = session
        self._users = users

    async def execute(self, command: UpdateProfileSettingsCommand) -> User:
        user = await get_user(self._users, command.user_id)
        if command.avatar_url is not None:
            user.avatar_url = command.avatar_url
        if command.timezone is not None:
            user.timezone = command.timezone
        if command.locale is not None:
            user.locale = command.locale
        user.updated_at = datetime.now(UTC)
        await self._session.commit()
        return user
