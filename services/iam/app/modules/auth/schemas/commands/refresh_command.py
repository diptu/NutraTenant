from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RefreshCommand:
    refresh_token: str
    ip_address: str | None
    user_agent: str | None
