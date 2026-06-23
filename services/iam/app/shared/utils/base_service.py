"""Base class every module's service extends — mirrors BaseRepository's role
for repositories. Deliberately minimal: every service's own `__init__` still
constructs its own repositories after calling `super().__init__(session)`;
this only factors out the one line every service already had in common.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class BaseService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
