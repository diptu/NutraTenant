from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VerifyMfaAndLoginCommand:
    mfa_challenge_token: str
    code: str
    ip_address: str | None
    user_agent: str | None
