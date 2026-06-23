from __future__ import annotations

from app.shared.exceptions.base import AlreadyExistsError, DomainError

__all__ = [
    "AccessApprovalNotFoundError",
    "AccessRequestAlreadyDecidedError",
    "AccessRequestNotFoundError",
    "AccessReviewNotFoundError",
]


class AccessRequestAlreadyDecidedError(AlreadyExistsError):
    """An access-approval was attempted against a request that's no longer
    ``PENDING_APPROVAL`` — a request can only be decided once."""


class AccessRequestNotFoundError(DomainError):
    pass


class AccessReviewNotFoundError(DomainError):
    pass


class AccessApprovalNotFoundError(DomainError):
    pass
