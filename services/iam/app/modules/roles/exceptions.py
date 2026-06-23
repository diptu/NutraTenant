from __future__ import annotations

from app.shared.exceptions.base import AlreadyExistsError, DomainError

__all__ = [
    "RoleAlreadyExistsError",
    "RoleInUseError",
    "RoleNotAssignedError",
    "RoleNotFoundError",
]


class RoleAlreadyExistsError(AlreadyExistsError):
    """A global role with this code already exists."""


class RoleInUseError(AlreadyExistsError):
    """A role can't be deleted while it's still assigned to at least one user."""


class RoleNotFoundError(DomainError):
    pass


class RoleNotAssignedError(DomainError):
    """The user does not currently hold the role being revoked/queried."""
