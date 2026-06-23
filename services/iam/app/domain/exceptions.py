"""Cross-cutting domain errors with no single owning module, plus
re-exports of the shared base classes every module's own exceptions.py
builds on.

``DomainError``/``AlreadyExistsError``/``ForbiddenError`` are re-exported
from app.shared.exceptions.base rather than redefined here: every domain's
exceptions must share the exact same base classes, or main.py's `isinstance`
checks silently stop matching half of them.
"""

from __future__ import annotations

from app.shared.exceptions.base import AlreadyExistsError, DomainError, ForbiddenError

__all__ = [
    "AlreadyExistsError",
    "DomainError",
    "ForbiddenError",
    "TenantContextRequiredError",
]


class TenantContextRequiredError(DomainError):
    """A direct user-permission grant (POST/DELETE /users/{id}/permissions)
    was attempted without a ``tenant_id`` query param, and the target user's
    organization memberships don't disambiguate which one to scope it to
    (they belong to zero, or more than one) — 400."""
