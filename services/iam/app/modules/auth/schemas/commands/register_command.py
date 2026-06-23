from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RegisterCommand:
    email: str
    password: str
    full_name: str | None
