from __future__ import annotations

from app.shared.exceptions.base import AlreadyExistsError, DomainError

__all__ = ["ResourceAlreadyExistsError", "ResourceNotFoundError"]


class ResourceAlreadyExistsError(AlreadyExistsError):
    """A resource with this name already exists."""


class ResourceNotFoundError(DomainError):
    pass
