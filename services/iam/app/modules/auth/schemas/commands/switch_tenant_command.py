from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.users.models import User


@dataclass(frozen=True, slots=True)
class SwitchTenantCommand:
    user: User
    tenant_slug: str
    ip_address: str | None
    user_agent: str | None
    current_refresh_token: str | None
