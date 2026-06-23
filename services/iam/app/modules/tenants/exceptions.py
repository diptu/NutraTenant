from __future__ import annotations

from app.shared.exceptions.base import AlreadyExistsError, DomainError

__all__ = [
    "OrganizationTenantLinkAlreadyExistsError",
    "OrganizationTenantLinkNotFoundError",
    "TenantAlreadyExistsError",
    "TenantNotFoundError",
]


class TenantAlreadyExistsError(AlreadyExistsError):
    """A tenant with this slug already exists."""


class TenantNotFoundError(DomainError):
    pass


class OrganizationTenantLinkAlreadyExistsError(AlreadyExistsError):
    """This organization is already linked to this tenant."""


class OrganizationTenantLinkNotFoundError(DomainError):
    """This organization is not currently linked to this tenant."""
