from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GoogleCallbackCommand:
    code: str
    state: str
    ip_address: str | None
    user_agent: str | None
