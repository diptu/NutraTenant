from __future__ import annotations

import uuid
from datetime import datetime

from app.core.config import Settings
from app.core.token_blacklist import TokenBlacklist


async def invalidate_access_tokens_issued_before(
    token_blacklist: TokenBlacklist, settings: Settings, user_id: uuid.UUID, when: datetime
) -> None:
    # NOTE: JWT `iat` is always encoded/decoded as an integer unix
    # timestamp, so a token issued in the *same wall-clock second* as
    # this call is ambiguous (its floored iat can't be ordered against
    # this precise timestamp). That's resolved in favor of security: an
    # old, stale token from that same second stays rejected rather than
    # risk it staying valid — a brand-new token minted in that same
    # second just has to be requested again a moment later, which is a
    # safe failure mode.
    ttl_seconds = settings.access_token_expire_minutes * 60
    await token_blacklist.set_invalidate_before(
        str(user_id), timestamp=when.timestamp(), ttl_seconds=ttl_seconds
    )
