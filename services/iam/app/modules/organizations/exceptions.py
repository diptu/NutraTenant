from __future__ import annotations

from app.shared.exceptions.base import AlreadyExistsError, DomainError

__all__ = [
    "InvitationNotFoundError",
    "LastOwnerError",
    "OrganizationAlreadyExistsError",
    "OrganizationNotFoundError",
    "UserAlreadyMemberError",
]


class OrganizationAlreadyExistsError(AlreadyExistsError):
    """An organization with this slug already exists."""


class UserAlreadyMemberError(AlreadyExistsError):
    """The user is already a member of this organization."""


class LastOwnerError(AlreadyExistsError):
    """An organization can't be left without at least one owner — refuse to
    remove or demote its last remaining owner."""


class OrganizationNotFoundError(DomainError):
    pass


class InvitationNotFoundError(DomainError):
    pass
