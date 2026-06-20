"""Google OAuth2/OIDC client — authorization URL, code exchange, ID token verification.

Deliberately hand-rolled against Google's stable, documented endpoints
rather than pulling in `google-auth`/`authlib`: this keeps the whole
federation flow in plain httpx + PyJWT + cryptography, which is both the
$0/dependency-light path and the most direct one to unit test — every
network call goes through httpx, so respx can intercept all of it (PyJWT's
own `PyJWKClient` deliberately isn't used here: it fetches keys via
`urllib`, which respx can't see).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from app.core.config import Settings
from app.domain.exceptions import GoogleTokenVerificationError

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

    async def verify_id_token(
        self, id_token: str, *, expected_nonce: str
    ) -> GoogleIdentity:
        try:
            unverified_header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise GoogleTokenVerificationError(
                "Google ID token has a malformed header"
            ) from exc

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
            raise GoogleTokenVerificationError(
                "Google ID token failed verification"
            ) from exc

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
            raise GoogleTokenVerificationError(
                f"Google ID token missing claim: {exc}"
            ) from exc

    async def _find_jwk(self, kid: str | None) -> dict[str, Any]:
        keys = await self._get_jwks()
        jwk = next((key for key in keys if key.get("kid") == kid), None)
        if jwk is None:
            raise GoogleTokenVerificationError(
                "No matching Google signing key for this ID token"
            )
        return jwk

    async def _get_jwks(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if (
            self._jwks_cache["keys"] is None
            or now - self._jwks_cache["fetched_at"] > _JWKS_CACHE_TTL_SECONDS
        ):
            async with httpx.AsyncClient() as client:
                response = await client.get(JWKS_URI)
            response.raise_for_status()
            self._jwks_cache["keys"] = response.json()["keys"]
            self._jwks_cache["fetched_at"] = now
        return self._jwks_cache["keys"]
