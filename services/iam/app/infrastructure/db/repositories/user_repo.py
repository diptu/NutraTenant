"""User repository, including the eager-loaded permission-resolution query."""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.infrastructure.db.models.associations import (
    RolePermission,
    UserOrganizationRole,
)
from app.infrastructure.db.models.role import Role
from app.infrastructure.db.models.user import User
from app.infrastructure.db.repositories.base_repository import BaseRepository


class UserRepository(BaseRepository[User]):
    """Persistence access for :class:`User`."""

    model = User

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_google_subject(self, subject: str) -> User | None:
        stmt = select(User).where(User.google_subject == subject)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def search(self, query: str, *, limit: int = 50) -> list[User]:
        pattern = f"%{query.lower()}%"
        stmt = (
            select(User)
            .where(or_(User.email.ilike(pattern), User.full_name.ilike(pattern)))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_with_org_roles(self, user_id: uuid.UUID) -> User | None:
        """Load a user plus its full role→permission chain in one round trip.

        This single query is what lets authorization checks avoid N+1 —
        ``org_roles``/``role``/``role_permissions``/``permission`` are all
        declared ``lazy="raise"`` on the models, so any code path that skips
        this eager-load chain fails loudly instead of issuing per-row queries.
        """
        stmt = (
            select(User)
            .where(User.id == user_id)
            .options(
                selectinload(User.org_roles)
                .selectinload(UserOrganizationRole.role)
                .selectinload(Role.role_permissions)
                .selectinload(RolePermission.permission)
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
