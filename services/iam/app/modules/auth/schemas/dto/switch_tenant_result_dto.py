from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.organizations.models import Organization
    from app.modules.roles.models import Role


@dataclass(frozen=True, slots=True)
class SwitchTenantResult:
    """``refresh_token`` is only set when the caller had a still-valid
    refresh token to rotate forward into the new tenant context (see
    ``SwitchTenantUseCase``) — ``None`` doesn't mean failure, just that
    there was nothing to rotate."""

    access_token: str
    refresh_token: str | None
    organization: Organization
    role: Role
