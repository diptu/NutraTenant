from __future__ import annotations

from datetime import UTC, datetime

from app.modules.users.models import User
from app.modules.users.repositories.interfaces.user_repository import UserRepository
from app.modules.users.schemas.commands.update_attributes_command import (
    UpdateAttributesCommand,
)
from app.modules.users.use_cases._lookups import get_user
from app.shared.value_objects import SubjectAttributes
from sqlalchemy.ext.asyncio import AsyncSession


class UpdateAttributesUseCase:
    """Merge ``patch`` into the user's ABAC attribute bag.

    Goes through SubjectAttributes so the same size cap that protects
    the JWT `attrs` claim (see app/domain/value_objects.py) also applies
    here — an admin can't grow a user's attribute bag past what's safe
    to embed in an access token.
    """

    def __init__(self, session: AsyncSession, users: UserRepository) -> None:
        self._session = session
        self._users = users

    async def execute(self, command: UpdateAttributesCommand) -> User:
        user = await get_user(self._users, command.user_id)
        merged = SubjectAttributes(user.attributes or {}).merged_with(command.patch)
        user.attributes = merged.values
        user.updated_at = datetime.now(UTC)
        await self._session.commit()
        return user
