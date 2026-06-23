from __future__ import annotations

import uuid

from app.modules.users.exceptions import UserNotFoundError
from app.modules.users.models import User
from app.modules.users.repositories.interfaces.user_repository import UserRepository


async def get_user(users: UserRepository, user_id: uuid.UUID) -> User:
    user = await users.get_by_id(user_id)
    if user is None:
        raise UserNotFoundError(f"No user with id '{user_id}'")
    return user
