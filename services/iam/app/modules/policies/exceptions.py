from __future__ import annotations

from app.shared.exceptions.base import AlreadyExistsError, DomainError

__all__ = ["InvalidPolicyConditionsError", "PolicyAlreadyExistsError", "PolicyNotFoundError"]


class PolicyAlreadyExistsError(AlreadyExistsError):
    """A policy with this name already exists."""


class PolicyNotFoundError(DomainError):
    pass


class InvalidPolicyConditionsError(DomainError):
    """A policy's ``conditions`` tree is structurally malformed — 400."""
