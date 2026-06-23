from __future__ import annotations

from app.shared.exceptions.base import AlreadyExistsError, DomainError

__all__ = ["PermissionAlreadyExistsError", "PermissionNotFoundError"]


class PermissionAlreadyExistsError(AlreadyExistsError):
    """A permission with this resource:action code already exists."""


class PermissionNotFoundError(DomainError):
    pass
