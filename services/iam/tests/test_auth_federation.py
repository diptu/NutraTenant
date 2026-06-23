"""Auth + Google OIDC federation: registration, login lockout, refresh token
rotation/reuse detection, logout revocation, and the full federated login flow
with Google's token/JWKS endpoints mocked via respx.

Uses its own `client` fixture (shadowing the one in conftest.py) for two
reasons: (1) it must run over `https://test` so httpx actually honours the
`Secure` flag on the refresh-token cookie — see the same workaround in
test_auth.py — and (2) it overrides `get_token_cache` with an in-memory
fake so nothing here needs a live Redis, mirroring how conftest already
swaps Postgres for in-memory SQLite.
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
from app.audit import AuditLog
from app.core.config import get_settings
from app.modules.auth.models import RefreshToken
from app.modules.auth.utils.oauth import JWKS_URI, TOKEN_ENDPOINT, InMemoryTokenCache
from app.modules.users.models import User
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import select

pytestmark = pytest.mark.anyio

_KID = "test-signing-key-1"
_GOOGLE_CLIENT_ID = "test-google-client-id-123"
_REGISTER_PAYLOAD = {
    "email": "alice@example.com",
    "password": "Sup3rSecret!23",
    "full_name": "Alice",
}


@pytest.fixture(autouse=True)
def _pin_google_client_id(monkeypatch):
    """`get_settings()` is process-wide lru_cached and app.main already calls it
    at import time, so the real services/iam/.env's GOOGLE_CLIENT_ID (blank in
    local dev) would otherwise leak into every test here — and PyJWT treats an
    empty `aud` claim as a *missing* claim, failing every token unconditionally.
    Pin it to a known value and bust the cache so both the signer (test) and
    the verifier (app) agree on a real audience.
    """
    monkeypatch.setenv("GOOGLE_CLIENT_ID", _GOOGLE_CLIENT_ID)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def client_ctx(app):
    """Same shape as conftest's `client`, but https:// + an in-memory token cache.

    https:// (not conftest's http://) so httpx actually honours the
    refresh cookie's `Secure` flag; the in-memory cache override means none
    of this needs a live Redis (see module docstring).
    """
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


def _sign_id_token(private_key, *, claims_overrides: dict | None = None, omit: tuple[str, ...] = ()):
    settings = get_settings()
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": settings.google_client_id,
        "sub": "google-subject-001",
        "email": "newgoogleuser@example.com",
        "email_verified": True,
        "name": "Google User",
        "nonce": "placeholder-nonce",
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(claims_overrides or {})
    for key in omit:
        claims.pop(key, None)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": _KID})


async def _start_google_login(client: AsyncClient) -> tuple[str, str]:
    response = await client.get("/api/v1/auth/google/login")
    assert response.status_code == 200
    authorization_url = response.json()["authorization_url"]
    query = parse_qs(urlsplit(authorization_url).query)
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
# Registration / login / audit log
# ---------------------------------------------------------------------------


async def test_register_creates_user_and_audit_log(client_ctx, db_session):
    response = await client_ctx.post("/api/v1/auth/register", json=_REGISTER_PAYLOAD)
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == _REGISTER_PAYLOAD["email"]
    assert body["attributes"] == {}

    logs = (
        (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "user.registered")))
        .scalars()
        .all()
    )
    assert len(logs) == 1
    assert str(logs[0].user_id) == body["id"]


async def test_register_duplicate_email_rejected(client_ctx):
    await client_ctx.post("/api/v1/auth/register", json=_REGISTER_PAYLOAD)
    response = await client_ctx.post("/api/v1/auth/register", json=_REGISTER_PAYLOAD)
    assert response.status_code == 409


async def test_login_success_sets_refresh_cookie_and_audit_log(client_ctx, db_session):
    await client_ctx.post("/api/v1/auth/register", json=_REGISTER_PAYLOAD)

    response = await client_ctx.post(
        "/api/v1/auth/login",
        json={
            "email": _REGISTER_PAYLOAD["email"],
            "password": _REGISTER_PAYLOAD["password"],
        },
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert "refresh_token" in response.cookies

    logs = (
        (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "auth.login.success")))
        .scalars()
        .all()
    )
    assert len(logs) == 1


async def test_login_wrong_password_records_failure_audit(client_ctx, db_session):
    await client_ctx.post("/api/v1/auth/register", json=_REGISTER_PAYLOAD)

    response = await client_ctx.post(
        "/api/v1/auth/login",
        json={"email": _REGISTER_PAYLOAD["email"], "password": "wrong-password"},
    )
    assert response.status_code == 401

    logs = (
        (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "auth.login.failure")))
        .scalars()
        .all()
    )
    assert len(logs) == 1


async def test_login_locks_account_after_max_attempts(client_ctx, db_session):
    settings = get_settings()
    await client_ctx.post("/api/v1/auth/register", json=_REGISTER_PAYLOAD)

    for _ in range(settings.lockout_max_attempts):
        await client_ctx.post(
            "/api/v1/auth/login",
            json={"email": _REGISTER_PAYLOAD["email"], "password": "wrong-password"},
        )

    # Even the *correct* password is now rejected while locked.
    response = await client_ctx.post(
        "/api/v1/auth/login",
        json={
            "email": _REGISTER_PAYLOAD["email"],
            "password": _REGISTER_PAYLOAD["password"],
        },
    )
    assert response.status_code == 423
    assert "Retry-After" in response.headers

    logs = (
        (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "auth.login.locked")))
        .scalars()
        .all()
    )
    assert len(logs) == 1


# ---------------------------------------------------------------------------
# Refresh token rotation + reuse detection
# ---------------------------------------------------------------------------


async def test_refresh_rotates_token_and_revokes_old_one(client_ctx, db_session):
    await client_ctx.post("/api/v1/auth/register", json=_REGISTER_PAYLOAD)
    login_response = await client_ctx.post(
        "/api/v1/auth/login",
        json={
            "email": _REGISTER_PAYLOAD["email"],
            "password": _REGISTER_PAYLOAD["password"],
        },
    )
    old_refresh_cookie = login_response.cookies["refresh_token"]

    refresh_response = await client_ctx.post("/api/v1/auth/refresh")
    assert refresh_response.status_code == 200
    new_refresh_cookie = refresh_response.cookies["refresh_token"]
    assert new_refresh_cookie != old_refresh_cookie

    rows = (await db_session.execute(select(RefreshToken))).scalars().all()
    assert len(rows) == 2
    old_row = next(r for r in rows if r.revoked_at is not None)
    new_row = next(r for r in rows if r.revoked_at is None)
    assert old_row.replaced_by_jti == new_row.id
    assert old_row.family_id == new_row.family_id


async def test_refresh_reuse_revokes_entire_family(client_ctx, db_session):
    await client_ctx.post("/api/v1/auth/register", json=_REGISTER_PAYLOAD)
    login_response = await client_ctx.post(
        "/api/v1/auth/login",
        json={
            "email": _REGISTER_PAYLOAD["email"],
            "password": _REGISTER_PAYLOAD["password"],
        },
    )
    original_cookie = login_response.cookies["refresh_token"]

    first_rotation = await client_ctx.post("/api/v1/auth/refresh")
    assert first_rotation.status_code == 200
    rotated_cookie = first_rotation.cookies["refresh_token"]

    # Replay the *original* (already-rotated-away) refresh token.
    client_ctx.cookies.set("refresh_token", original_cookie, path="/api/v1/auth")
    reuse_response = await client_ctx.post("/api/v1/auth/refresh")
    assert reuse_response.status_code == 401

    logs = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.event_type == "auth.refresh.reuse_detected")
            )
        )
        .scalars()
        .all()
    )
    assert len(logs) == 1

    # The token issued by the *legitimate* rotation is now also dead —
    # reuse revokes the whole family, not just the replayed token.
    client_ctx.cookies.set("refresh_token", rotated_cookie, path="/api/v1/auth")
    second_attempt = await client_ctx.post("/api/v1/auth/refresh")
    assert second_attempt.status_code == 401


async def test_refresh_without_cookie_rejected(client_ctx):
    response = await client_ctx.post("/api/v1/auth/refresh")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Logout: refresh family revocation + access token blacklist
# ---------------------------------------------------------------------------


async def test_logout_revokes_refresh_token(client_ctx, db_session):
    await client_ctx.post("/api/v1/auth/register", json=_REGISTER_PAYLOAD)
    login_response = await client_ctx.post(
        "/api/v1/auth/login",
        json={
            "email": _REGISTER_PAYLOAD["email"],
            "password": _REGISTER_PAYLOAD["password"],
        },
    )
    access_token = login_response.json()["access_token"]

    logout_response = await client_ctx.post(
        "/api/v1/auth/logout", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert logout_response.status_code == 204

    refresh_response = await client_ctx.post("/api/v1/auth/refresh")
    assert refresh_response.status_code == 401


async def test_access_token_blacklisted_after_logout_rejected_by_get_current_user(
    client_ctx,
):
    """Exercises get_current_user directly via a protected dependency override-free path."""
    from app.api.v1.dependencies import get_current_user
    from app.main import app as app_instance
    from fastapi import APIRouter, Depends

    probe_router = APIRouter()

    @probe_router.get("/__probe/me")
    async def _probe(user: User = Depends(get_current_user)):
        return {"id": str(user.id)}

    app_instance.include_router(probe_router)

    await client_ctx.post("/api/v1/auth/register", json=_REGISTER_PAYLOAD)
    login_response = await client_ctx.post(
        "/api/v1/auth/login",
        json={
            "email": _REGISTER_PAYLOAD["email"],
            "password": _REGISTER_PAYLOAD["password"],
        },
    )
    access_token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    ok = await client_ctx.get("/__probe/me", headers=headers)
    assert ok.status_code == 200

    await client_ctx.post("/api/v1/auth/logout", headers=headers)

    revoked = await client_ctx.get("/__probe/me", headers=headers)
    assert revoked.status_code == 401


# ---------------------------------------------------------------------------
# Google OIDC federation
# ---------------------------------------------------------------------------


async def test_google_login_returns_authorization_url_with_state_and_nonce(client_ctx):
    state, nonce = await _start_google_login(client_ctx)
    assert state
    assert nonce
    assert state != nonce


@respx.mock
async def test_google_callback_new_identity_registers_user(
    client_ctx, db_session, google_keypair, google_jwks
):
    private_key, _ = google_keypair
    state, nonce = await _start_google_login(client_ctx)
    id_token = _sign_id_token(private_key, claims_overrides={"nonce": nonce})

    _mock_jwks(respx, google_jwks)
    _mock_token_endpoint(respx, id_token)

    response = await client_ctx.get(
        "/api/v1/auth/google/callback",
        params={"code": "fake-auth-code", "state": state},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()
    assert "refresh_token" in response.cookies

    user = (
        await db_session.execute(select(User).where(User.email == "newgoogleuser@example.com"))
    ).scalar_one()
    assert user.google_subject == "google-subject-001"
    assert user.password_hash is None

    logs = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.event_type == "auth.google_login.registered")
            )
        )
        .scalars()
        .all()
    )
    assert len(logs) == 1


@respx.mock
async def test_google_callback_links_existing_verified_email_account(
    client_ctx, db_session, google_keypair, google_jwks
):
    private_key, _ = google_keypair
    await client_ctx.post(
        "/api/v1/auth/register",
        json={
            "email": "newgoogleuser@example.com",
            "password": "Sup3rSecret!23",
            "full_name": "Existing",
        },
    )

    state, nonce = await _start_google_login(client_ctx)
    id_token = _sign_id_token(private_key, claims_overrides={"nonce": nonce})

    _mock_jwks(respx, google_jwks)
    _mock_token_endpoint(respx, id_token)

    response = await client_ctx.get(
        "/api/v1/auth/google/callback",
        params={"code": "fake-auth-code", "state": state},
    )
    assert response.status_code == 200

    user = (
        await db_session.execute(select(User).where(User.email == "newgoogleuser@example.com"))
    ).scalar_one()
    assert user.google_subject == "google-subject-001"
    assert user.password_hash is not None  # the original local credential survives linking

    logs = (
        (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "auth.google_login.linked")))
        .scalars()
        .all()
    )
    assert len(logs) == 1


@respx.mock
async def test_google_callback_refuses_to_link_unverified_email(
    client_ctx, db_session, google_keypair, google_jwks
):
    """The account-takeover guard: an unverified email match must never auto-link."""
    private_key, _ = google_keypair
    await client_ctx.post(
        "/api/v1/auth/register",
        json={
            "email": "newgoogleuser@example.com",
            "password": "Sup3rSecret!23",
            "full_name": "Victim",
        },
    )

    state, nonce = await _start_google_login(client_ctx)
    id_token = _sign_id_token(private_key, claims_overrides={"nonce": nonce, "email_verified": False})

    _mock_jwks(respx, google_jwks)
    _mock_token_endpoint(respx, id_token)

    response = await client_ctx.get(
        "/api/v1/auth/google/callback",
        params={"code": "fake-auth-code", "state": state},
    )
    assert response.status_code == 401

    user = (
        await db_session.execute(select(User).where(User.email == "newgoogleuser@example.com"))
    ).scalar_one()
    assert user.google_subject is None

    logs = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.event_type == "auth.google_login.link_refused_unverified_email"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(logs) == 1


@respx.mock
async def test_google_callback_missing_email_claim_rejected(client_ctx, google_keypair, google_jwks):
    """Schema validation edge case: a structurally-valid-but-incomplete ID token."""
    private_key, _ = google_keypair
    state, nonce = await _start_google_login(client_ctx)
    id_token = _sign_id_token(private_key, claims_overrides={"nonce": nonce}, omit=("email",))

    _mock_jwks(respx, google_jwks)
    _mock_token_endpoint(respx, id_token)

    response = await client_ctx.get(
        "/api/v1/auth/google/callback",
        params={"code": "fake-auth-code", "state": state},
    )
    assert response.status_code == 401


@respx.mock
async def test_google_callback_nonce_mismatch_rejected(client_ctx, google_keypair, google_jwks):
    private_key, _ = google_keypair
    state, _real_nonce = await _start_google_login(client_ctx)
    id_token = _sign_id_token(private_key, claims_overrides={"nonce": "a-completely-different-nonce"})

    _mock_jwks(respx, google_jwks)
    _mock_token_endpoint(respx, id_token)

    response = await client_ctx.get(
        "/api/v1/auth/google/callback",
        params={"code": "fake-auth-code", "state": state},
    )
    assert response.status_code == 401


async def test_google_callback_unknown_state_rejected(client_ctx):
    response = await client_ctx.get(
        "/api/v1/auth/google/callback",
        params={"code": "fake-auth-code", "state": f"never-issued-{uuid4()}"},
    )
    assert response.status_code == 401


@respx.mock
async def test_google_callback_state_replay_rejected(client_ctx, google_keypair, google_jwks):
    """A state token is single-use — the second callback with the same state must fail
    even though the first one succeeded."""
    private_key, _ = google_keypair
    state, nonce = await _start_google_login(client_ctx)
    id_token = _sign_id_token(private_key, claims_overrides={"nonce": nonce})

    _mock_jwks(respx, google_jwks)
    _mock_token_endpoint(respx, id_token)

    first = await client_ctx.get(
        "/api/v1/auth/google/callback",
        params={"code": "fake-auth-code", "state": state},
    )
    assert first.status_code == 200

    second = await client_ctx.get(
        "/api/v1/auth/google/callback",
        params={"code": "fake-auth-code", "state": state},
    )
    assert second.status_code == 401


@respx.mock
async def test_google_callback_bad_signature_rejected(client_ctx, google_jwks):
    """ID token signed by a key Google's JWKS doesn't actually contain."""
    state, nonce = await _start_google_login(client_ctx)
    rogue_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    id_token = _sign_id_token(rogue_key, claims_overrides={"nonce": nonce})

    _mock_jwks(respx, google_jwks)  # JWKS only contains the *legitimate* key
    _mock_token_endpoint(respx, id_token)

    response = await client_ctx.get(
        "/api/v1/auth/google/callback",
        params={"code": "fake-auth-code", "state": state},
    )
    assert response.status_code == 401
