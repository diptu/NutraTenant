from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.organizations.models import Organization
    from app.modules.roles.models import Role


@dataclass(frozen=True, slots=True)
class ProfileContext:
    """The tenant/role/permissions a user's *current session* is bound to —
    empty when the access token carries no tenant_id claim, or when the
    membership it named has since been revoked (dropped silently, same
    tolerant pattern as AuthService.verify_mfa_and_login)."""

    organization: Organization | None = None
    role: Role | None = None
    permissions: list[str] = field(default_factory=list)
