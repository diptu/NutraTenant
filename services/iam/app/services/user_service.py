"""User CRUD, search, activation, and ABAC attribute management."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.domain.exceptions import UserNotFoundError
from app.domain.value_objects import SubjectAttributes
from app.infrastructure.db.models.user import User
from app.infrastructure.db.repositories.user_repo import UserRepository


class UserService:
    def __init__(self, session) -> None:
        self._session = session
        self._users = UserRepository(session)

    async def get_by_id(self, user_id: uuid.UUID) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(f"No user with id '{user_id}'")
        return user

    async def search(
        self, query: str | None, *, limit: int = 50, offset: int = 0
    ) -> list[User]:
        if query:
            return await self._users.search(query, limit=limit)
        return await self._users.list_all(limit=limit, offset=offset)

    async def update_profile(
        self, user_id: uuid.UUID, *, full_name: str | None
    ) -> User:
        user = await self.get_by_id(user_id)
        user.full_name = full_name
        user.updated_at = datetime.now(UTC)
        await self._session.commit()
        return user

    async def update_attributes(self, user_id: uuid.UUID, patch: dict) -> User:
        """Merge `patch` into the user's ABAC attribute bag.

        Goes through SubjectAttributes so the same size cap that protects
        the JWT `attrs` claim (see app/domain/value_objects.py) also applies
        here — an admin can't grow a user's attribute bag past what's safe
        to embed in an access token.
        """
        user = await self.get_by_id(user_id)
        merged = SubjectAttributes(user.attributes or {}).merged_with(patch)
        user.attributes = merged.values
        user.updated_at = datetime.now(UTC)
        await self._session.commit()
        return user

    async def set_active(self, user_id: uuid.UUID, *, is_active: bool) -> User:
        user = await self.get_by_id(user_id)
        user.is_active = is_active
        user.updated_at = datetime.now(UTC)
        await self._session.commit()
        return user

    async def delete(self, user_id: uuid.UUID) -> None:
        user = await self.get_by_id(user_id)
        await self._users.delete(user)
        await self._session.commit()
