from __future__ import annotations

from app.shared.exceptions.base import AlreadyExistsError, DomainError

__all__ = [
    "GroupMembershipAlreadyExistsError",
    "GroupMembershipNotFoundError",
    "GroupNotFoundError",
    "GroupTenantRequiredError",
    "InvalidGroupHierarchyError",
]


class GroupMembershipAlreadyExistsError(AlreadyExistsError):
    """This user already has a membership record for this group."""


class GroupNotFoundError(DomainError):
    pass


class GroupMembershipNotFoundError(DomainError):
    pass


class InvalidGroupHierarchyError(DomainError):
    """A group's ``parent_group_id`` is invalid — points at itself, at a
    group in a different tenant, or would close a cycle in the parent
    chain — 400."""


class GroupTenantRequiredError(DomainError):
    """A group (or membership) create was attempted with no resolvable
    tenant — no explicit ``tenant_id`` and no tenant on the caller's
    session — 400."""
