from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LoginCommand:
    email: str
    password: str
    ip_address: str | None
    user_agent: str | None
    tenant_id: str | None = None
