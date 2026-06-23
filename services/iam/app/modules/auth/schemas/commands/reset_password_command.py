from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResetPasswordCommand:
    raw_token: str
    new_password: str
