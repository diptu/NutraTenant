"""
Google OAuth2/OIDC endpoint tests.

tests/test_auth_federation.py already covers the core federation flow
exhaustively (new-identity registration, existing-account linking,
unverified-email link refusal, nonce mismatch, state replay, bad
signature — all with DB/audit-log assertions). This file sticks to what
isn't covered there: the account-conflict 409 (two different Google subs
claiming the same email), the `error`/missing-param callback paths, the
JWKS cache actually skipping a re-fetch on a warm cache, the `/login/redirect`
convenience endpoint, and the OpenAPI schema entries for these routes.

Reuses the same respx + RSA-signed-ID-token pattern as test_auth_federation.py,
and the same `client_ctx` (https:// + in-memory token cache, since
OAuthStateStore goes through `get_token_cache`, which is Redis-backed with
no in-memory fallback unless overridden).
"""

from __future__ import annotations

import json
import time
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import jwt
import pytest
import respx
from app.api.v1.dependencies import get_token_cache
from app.core.config import get_settings
from app.modules.auth.utils.oauth import JWKS_URI, TOKEN_ENDPOINT, InMemoryTokenCache
from app.modules.users.models import User
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import select

pytestmark = pytest.mark.anyio

_KID = "test-signing-key-1"
_GOOGLE_CLIENT_ID = "test-google-client-id-456"


@pytest.fixture(autouse=True)
def _pin_google_client_id(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", _GOOGLE_CLIENT_ID)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def client_ctx(app):
    cache = InMemoryTokenCache()
    app.dependency_overrides[get_token_cache] = lambda: cache
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as ac:
        yield ac


@pytest.fixture(scope="module")
def google_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture
def google_jwks(google_keypair):
    _, public_key = google_keypair
    jwk = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk.update(kid=_KID, use="sig", alg="RS256")
    return {"keys": [jwk]}


def _sign_id_token(private_key, *, sub: str, email: str, nonce: str, email_verified: bool = True):
    settings = get_settings()
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": settings.google_client_id,
        "sub": sub,
        "email": email,
        "email_verified": email_verified,
        "name": "Google User",
        "nonce": nonce,
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": _KID})


async def _start_google_login(client: AsyncClient) -> tuple[str, str]:
    response = await client.get("/api/v1/auth/google/login")
    assert response.status_code == 200
    query = parse_qs(urlsplit(response.json()["authorization_url"]).query)
    return query["state"][0], query["nonce"][0]


def _mock_token_endpoint(respx_mock, id_token: str) -> None:
    respx_mock.post(TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "id_token": id_token,
                "access_token": "ya29.fake",
                "expires_in": 3600,
            },
        )
    )


def _mock_jwks(respx_mock, jwks: dict) -> None:
    respx_mock.get(JWKS_URI).mock(return_value=httpx.Response(200, json=jwks))


# ---------------------------------------------------------------------------
# Account-conflict guard: two different Google identities, same email
# ---------------------------------------------------------------------------


@respx.mock
async def test_callback_conflict_returns_409_for_different_sub_same_email(
    client_ctx, db_session, google_keypair, google_jwks
):
    private_key, _ = google_keypair
    email = f"conflict-{uuid4().hex[:6]}@gmail.com"

    state, nonce = await _start_google_login(client_ctx)
    _mock_jwks(respx, google_jwks)
    _mock_token_endpoint(respx, _sign_id_token(private_key, sub="sub_A", email=email, nonce=nonce))
    first = await client_ctx.get("/api/v1/auth/google/callback", params={"code": "c1", "state": state})
    assert first.status_code == 200

    state2, nonce2 = await _start_google_login(client_ctx)
    _mock_token_endpoint(respx, _sign_id_token(private_key, sub="sub_B", email=email, nonce=nonce2))
    second = await client_ctx.get("/api/v1/auth/google/callback", params={"code": "c2", "state": state2})
    assert second.status_code == 409

    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    assert user.google_subject == "sub_A"  # the conflicting second sub never overwrote it


# ---------------------------------------------------------------------------
# Callback — missing params / explicit Google error
# ---------------------------------------------------------------------------


class TestGoogleCallbackErrorParams:
    async def test_google_error_param_returns_400(self, client_ctx):
        response = await client_ctx.get(
            "/api/v1/auth/google/callback",
            params={"error": "access_denied", "state": "irrelevant"},
        )
        assert response.status_code == 400
        assert "access_denied" in response.json()["detail"]

    async def test_missing_code_returns_400(self, client_ctx):
        state, _nonce = await _start_google_login(client_ctx)
        response = await client_ctx.get("/api/v1/auth/google/callback", params={"state": state})
        assert response.status_code == 400

    async def test_missing_state_returns_400(self, client_ctx):
        response = await client_ctx.get("/api/v1/auth/google/callback", params={"code": "c"})
        assert response.status_code == 400

    async def test_unknown_state_returns_401(self, client_ctx):
        """A syntactically-present but never-issued state goes through
        handle_callback and fails state lookup — OAuthStateError -> 401,
        distinct from the missing-param 400s above."""
        response = await client_ctx.get(
            "/api/v1/auth/google/callback",
            params={"code": "c", "state": f"never-issued-{uuid4()}"},
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Login redirect convenience endpoint
# ---------------------------------------------------------------------------


class TestGoogleLoginRedirect:
    async def test_redirect_variant_returns_302_to_google(self, client_ctx):
        response = await client_ctx.get("/api/v1/auth/google/login/redirect", follow_redirects=False)
        assert response.status_code == 302
        assert "accounts.google.com" in response.headers["location"]


# ---------------------------------------------------------------------------
# JWKS caching
# ---------------------------------------------------------------------------


class TestJwksCache:
    @respx.mock
    async def test_warm_cache_skips_second_fetch(self, client_ctx, google_keypair, google_jwks):
        private_key, _ = google_keypair
        jwks_route = respx.get(JWKS_URI).mock(return_value=httpx.Response(200, json=google_jwks))

        for i in range(2):
            state, nonce = await _start_google_login(client_ctx)
            id_token = _sign_id_token(
                private_key,
                sub=f"repeat-sub-{i}",
                email=f"repeat{i}@gmail.com",
                nonce=nonce,
            )
            _mock_token_endpoint(respx, id_token)
            response = await client_ctx.get(
                "/api/v1/auth/google/callback", params={"code": "c", "state": state}
            )
            assert response.status_code == 200

        # get_oidc_client is process-cached (see app/api/v1/dependencies.py)
        # so both callbacks share the same GoogleOIDCClient and its
        # in-memory JWKS cache — the second callback's verify_id_token call
        # must not trigger a second JWKS HTTP fetch.
        assert jwks_route.call_count == 1


# ---------------------------------------------------------------------------
# OpenAPI schema regression
# ---------------------------------------------------------------------------


class TestGoogleAuthOpenApiSchema:
    async def test_login_route_in_openapi(self, client_ctx):
        response = await client_ctx.get("/openapi.json")
        assert "/api/v1/auth/google/login" in response.json()["paths"]

    async def test_callback_route_in_openapi(self, client_ctx):
        response = await client_ctx.get("/openapi.json")
        assert "/api/v1/auth/google/callback" in response.json()["paths"]
