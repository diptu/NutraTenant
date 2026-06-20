"""CSRF state + replay-bound nonce for the Google OIDC authorization code flow.

`state` is the CSRF token round-tripped through the browser redirect;
`nonce` is bound into the ID token itself and checked against the claim
Google signs, so a stolen authorization `code` can't be replayed against a
different in-flight login attempt. Both are single-use: ``consume`` pops
the entry so a replayed callback always fails the second time.
"""

from __future__ import annotations

import secrets

from app.domain.exceptions import OAuthStateError
from app.infrastructure.security.token_cache import TokenCache

_KEY_PREFIX = "oauth:google:state:"


class OAuthStateStore:
    def __init__(self, cache: TokenCache, *, ttl_seconds: int) -> None:
        self._cache = cache
        self._ttl_seconds = ttl_seconds

    async def issue(self) -> tuple[str, str]:
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        await self._cache.set(_KEY_PREFIX + state, nonce, ttl_seconds=self._ttl_seconds)
        return state, nonce

    async def consume(self, state: str) -> str:
        nonce = await self._cache.pop(_KEY_PREFIX + state)
        if nonce is None:
            raise OAuthStateError("OAuth state is missing, expired, or already used")
        return nonce
