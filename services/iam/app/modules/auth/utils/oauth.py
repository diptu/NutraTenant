"""Google OAuth2/OIDC: the client (authorization URL, code exchange, ID
token verification), the CSRF state/nonce store, and the key/value-with-TTL
cache abstraction they're both built on — kept together since none of the
three is independently useful outside the Google federation flow.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.parse import urlencode

import httpx
import jwt
from app.core.config import Settings
from app.modules.auth.exceptions import GoogleTokenVerificationError, OAuthStateError
from jwt.algorithms import RSAAlgorithm
from redis.asyncio import Redis

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 - endpoint URL, not a secret
JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
_VALID_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
_JWKS_CACHE_TTL_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    subject: str
    email: str
    email_verified: bool
    name: str | None


class GoogleOIDCClient:
    """Deliberately hand-rolled against Google's stable, documented endpoints
    rather than pulling in `google-auth`/`authlib`: this keeps the whole
    federation flow in plain httpx + PyJWT + cryptography, which is both the
    $0/dependency-light path and the most direct one to unit test — every
    network call goes through httpx, so respx can intercept all of it (PyJWT's
    own `PyJWKClient` deliberately isn't used here: it fetches keys via
    `urllib`, which respx can't see)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._jwks_cache: dict[str, Any] = {"keys": None, "fetched_at": 0.0}

    def build_authorization_url(self, *, state: str, nonce: str) -> str:
        params = {
            "client_id": self._settings.google_client_id,
            "redirect_uri": self._settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "access_type": "online",
            "prompt": "select_account",
        }
        return f"{AUTHORIZATION_ENDPOINT}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": self._settings.google_client_id,
                    "client_secret": self._settings.google_client_secret,
                    "redirect_uri": self._settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        if response.status_code != httpx.codes.OK:
            raise GoogleTokenVerificationError(
                f"Google token exchange failed with status {response.status_code}"
            )
        return response.json()

    async def verify_id_token(self, id_token: str, *, expected_nonce: str) -> GoogleIdentity:
        try:
            unverified_header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise GoogleTokenVerificationError("Google ID token has a malformed header") from exc

        jwk = await self._find_jwk(unverified_header.get("kid"))
        public_key = RSAAlgorithm.from_jwk(json.dumps(jwk))

        try:
            claims = jwt.decode(
                id_token,
                key=public_key,  # type: ignore[arg-type]
                algorithms=["RS256"],
                audience=self._settings.google_client_id,
                issuer=list(_VALID_ISSUERS),
            )
        except jwt.PyJWTError as exc:
            raise GoogleTokenVerificationError("Google ID token failed verification") from exc

        if claims.get("nonce") != expected_nonce:
            raise GoogleTokenVerificationError("Google ID token nonce does not match")

        try:
            return GoogleIdentity(
                subject=claims["sub"],
                email=claims["email"],
                email_verified=bool(claims.get("email_verified", False)),
                name=claims.get("name"),
            )
        except KeyError as exc:
            raise GoogleTokenVerificationError(f"Google ID token missing claim: {exc}") from exc

    async def _find_jwk(self, kid: str | None) -> dict[str, Any]:
        keys = await self._get_jwks()
        jwk = next((key for key in keys if key.get("kid") == kid), None)
        if jwk is None:
            raise GoogleTokenVerificationError("No matching Google signing key for this ID token")
        return jwk

    async def _get_jwks(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._jwks_cache["keys"] is None or now - self._jwks_cache["fetched_at"] > _JWKS_CACHE_TTL_SECONDS:
            async with httpx.AsyncClient() as client:
                response = await client.get(JWKS_URI)
            response.raise_for_status()
            self._jwks_cache["keys"] = response.json()["keys"]
            self._jwks_cache["fetched_at"] = now
        return self._jwks_cache["keys"]


class TokenCache(Protocol):
    """Minimal async key/value-with-TTL cache abstraction. Two
    implementations: a real Redis-backed one for the running service, and an
    in-memory one used in tests so the suite never needs a live Redis
    instance — mirroring how tests/conftest.py already swaps Postgres for an
    in-memory SQLite engine rather than requiring a real database."""

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None: ...

    async def get(self, key: str) -> str | None: ...

    async def pop(self, key: str) -> str | None:
        """Atomically read-then-delete — used for single-use values like OAuth state."""
        ...

    async def delete(self, key: str) -> None: ...


class RedisTokenCache:
    """Assumes the Redis client was constructed with `decode_responses=True`
    (see app/auth/dependencies.py) — the redis-py stubs can't express that
    statically, hence the casts."""

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        await self._redis.set(key, value, ex=ttl_seconds)

    async def get(self, key: str) -> str | None:
        return cast("str | None", await self._redis.get(key))

    async def pop(self, key: str) -> str | None:
        return cast("str | None", await self._redis.getdel(key))

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)


class InMemoryTokenCache:
    """Process-local fallback — used by tests and any environment without Redis."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float]] = {}

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        self._store[key] = (value, time.monotonic() + ttl_seconds)

    async def get(self, key: str) -> str | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    async def pop(self, key: str) -> str | None:
        value = await self.get(key)
        self._store.pop(key, None)
        return value

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


_KEY_PREFIX = "oauth:google:state:"


class OAuthStateStore:
    """CSRF state + replay-bound nonce for the Google OIDC authorization code
    flow. `state` is the CSRF token round-tripped through the browser
    redirect; `nonce` is bound into the ID token itself and checked against
    the claim Google signs, so a stolen authorization `code` can't be
    replayed against a different in-flight login attempt. Both are
    single-use: ``consume`` pops the entry so a replayed callback always
    fails the second time."""

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
