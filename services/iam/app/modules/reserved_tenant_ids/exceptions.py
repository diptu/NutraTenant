from __future__ import annotations

from app.shared.exceptions.base import AlreadyExistsError, DomainError

__all__ = [
    "ReservedTenantIdAlreadyExistsError",
    "ReservedTenantIdError",
    "ReservedTenantIdNotFoundError",
]


class ReservedTenantIdError(AlreadyExistsError):
    """This tenant_id (Organization.slug) is on the reserved blocklist —
    it can never be claimed, whether or not an organization with that slug
    already exists."""


class ReservedTenantIdAlreadyExistsError(AlreadyExistsError):
    """This tenant_id is already on the reserved blocklist."""


class ReservedTenantIdNotFoundError(DomainError):
    pass
