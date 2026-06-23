from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.organizations.models import Organization
    from app.modules.roles.models import Role
    from app.modules.users.models import User


@dataclass(frozen=True, slots=True)
class TenantBootstrapResult:
    """``invite_token`` is only set when ``is_new_owner`` is True — an
    already-existing owner is mapped into the new tenant immediately, with
    nothing to redeem (see ``AuthService.create_tenant``)."""

    organization: Organization
    owner: User
    owner_role: Role
    is_new_owner: bool
    invite_token: str | None
