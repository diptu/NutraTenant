from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TokenPair:
    """The output of one token-pair issuance — login, the post-MFA verify
    step, or a refresh rotation. ``session_id`` is the new refresh token's
    own ``jti``; there's no separate sessions table, the refresh_tokens row
    *is* the durable session record (see RefreshToken)."""

    access_token: str
    refresh_token: str
    session_id: uuid.UUID
    issued_at: datetime
    expires_at: datetime
