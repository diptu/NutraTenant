from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LogoutCommand:
    refresh_token: str | None
    access_token: str | None
