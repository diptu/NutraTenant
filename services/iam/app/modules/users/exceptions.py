"""Users-domain errors."""

from __future__ import annotations

from app.shared.exceptions.base import DomainError


class UserNotFoundError(DomainError):
    pass
