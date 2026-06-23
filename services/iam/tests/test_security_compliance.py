"""
Section 9 security hardening tests: login rate limiting, account lockout
with exponential backoff, access-token revocation (logout jti-blacklist +
password-change/reset invalidate_before horizon), security headers, and CORS.

Updated to the current DDD architecture: JSON login, `app.core.rate_limit`
(InMemoryRateLimiter/RedisRateLimiter, not module-global ACTIVE_REFRESH_TOKENS),
`app.core.token_blacklist` (jti blacklist + per-user invalidate_before, not a
single dict), audit events checked via the `audit_logs` table rather than a
mocked AuditLogger singleton, and `/health` for the headers checks.
"""

from __future__ import annotations

import asyncio

import pytest
from app.audit import AuditLog
from app.core.config import get_settings
from app.core.rate_limit import (
    InMemoryRateLimiter,
    RedisRateLimiter,
    get_rate_limiter,
)
from app.core.token_blacklist import (
    InMemoryTokenBlacklist,
    RedisTokenBlacklist,
    get_token_blacklist,
)
from app.modules.users.models import User
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

_PASSWORD = "StrongPassw0rd!"


@pytest.fixture(autouse=True)
def _reset_singletons():
    """The conftest `app` fixture resets these too, but several tests in this
    file (the unit-level Redis-fallback tests) don't depend on `app`/`client`
    at all, so without this they can see a singleton instance left over from
    a previous test in the same class."""
    from app.core.rate_limit import reset_rate_limiter
    from app.core.token_blacklist import reset_token_blacklist

    reset_rate_limiter()
    reset_token_blacklist()
    yield
    reset_rate_limiter()
    reset_token_blacklist()


@pytest.fixture
async def client(app):
    """Shadows conftest's `client` (http://test) with an https:// base URL —
    several tests here round-trip the Secure refresh cookie across requests
    on the same client, which httpx only honours over https (see the same
    workaround in tests/test_auth.py)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as ac:
        yield ac


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str, password: str = _PASSWORD) -> dict:
    resp = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _login(client, email: str, password: str = _PASSWORD):
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def _me(client, access_token: str):
    return await client.get("/api/v1/users/me", headers=_auth(access_token))


def _build_bare_protected_app(*, token_blacklist_override, async_db_override) -> FastAPI:
    """Exercises get_current_user (the production dependency, which already
    checks the token blacklist) directly, without JWTContextMiddleware —
    mirrors the legacy intent of testing "the non-middleware-cached decode
    path" using this codebase's actual auth dependency rather than a
    parallel `is_authenticated` primitive that doesn't exist here.

    This is a brand-new FastAPI app, not `app_instance` — it needs its own
    `get_async_db` (no real Postgres here) and `get_token_blacklist` (no
    real Redis either) overrides passed in rather than inheriting the main
    app's.
    """
    from app.core.token_blacklist import get_token_blacklist
    from app.domain.exceptions import DomainError
    from app.main import _domain_error_handler
    from app.modules.auth.dependencies import get_async_db, get_current_user

    bare_app = FastAPI()
    bare_app.add_exception_handler(DomainError, _domain_error_handler)
    bare_app.dependency_overrides[get_token_blacklist] = token_blacklist_override
    bare_app.dependency_overrides[get_async_db] = async_db_override

    @bare_app.get("/protected")
    async def protected(user: User = Depends(get_current_user)) -> dict:
        return {"ok": True, "sub": str(user.id)}

    return bare_app


# ---------------------------------------------------------------------------
# Rate limiter — unit level (deterministic via monkeypatched monotonic clock)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestRateLimiterUnit:
    async def test_allows_up_to_limit_then_blocks(self) -> None:
        limiter = InMemoryRateLimiter()
        for _ in range(3):
            result = await limiter.hit("k", limit=3, window_seconds=60)
            assert result.allowed
        blocked = await limiter.hit("k", limit=3, window_seconds=60)
        assert not blocked.allowed
        assert blocked.retry_after_seconds > 0

    async def test_window_resets_after_expiry(self, monkeypatch) -> None:
        limiter = InMemoryRateLimiter()
        clock = {"t": 0.0}
        monkeypatch.setattr("app.core.rate_limit.time.monotonic", lambda: clock["t"])

        for _ in range(2):
            assert (await limiter.hit("k", limit=2, window_seconds=10)).allowed
        assert not (await limiter.hit("k", limit=2, window_seconds=10)).allowed

        clock["t"] = 11.0
        assert (await limiter.hit("k", limit=2, window_seconds=10)).allowed

    async def test_keys_are_isolated(self) -> None:
        limiter = InMemoryRateLimiter()
        for _ in range(2):
            assert (await limiter.hit("a", limit=2, window_seconds=60)).allowed
        assert not (await limiter.hit("a", limit=2, window_seconds=60)).allowed
        assert (await limiter.hit("b", limit=2, window_seconds=60)).allowed

    async def test_redis_construction_failure_falls_back_to_in_memory(self, monkeypatch) -> None:
        monkeypatch.setattr(get_settings(), "redis_url", "not a valid redis url")
        assert isinstance(get_rate_limiter(), InMemoryRateLimiter)

    async def test_redis_url_configured_builds_redis_backend(self, monkeypatch) -> None:
        monkeypatch.setattr(get_settings(), "redis_url", "redis://localhost:6379/0")
        assert isinstance(get_rate_limiter(), RedisRateLimiter)


# ---------------------------------------------------------------------------
# Login rate limiting — end-to-end through AuthService.login()
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestLoginRateLimitIntegration:
    async def test_exhaustion_returns_429_with_retry_after_and_audit(self, client, db_session) -> None:
        settings = get_settings()
        email = "ratelimit-exhaustion@example.com"

        for _ in range(settings.rate_limit_max_requests):
            resp = await _login(client, email, "wrong")
            assert resp.status_code == 401

        blocked = await _login(client, email, "wrong")
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers

        logs = (
            (
                await db_session.execute(
                    select(AuditLog).where(AuditLog.event_type == "auth.login.rate_limited")
                )
            )
            .scalars()
            .all()
        )
        assert len(logs) == 1

    async def test_rate_limit_is_per_email_not_global(self, client) -> None:
        settings = get_settings()
        email_a = "ratelimit-a@example.com"
        email_b = "ratelimit-b@example.com"

        for _ in range(settings.rate_limit_max_requests):
            resp = await _login(client, email_a, "wrong")
            assert resp.status_code == 401
        blocked = await _login(client, email_a, "wrong")
        assert blocked.status_code == 429

        still_ok = await _login(client, email_b, "wrong")
        assert still_ok.status_code == 401


# ---------------------------------------------------------------------------
# Account lockout — exponential backoff on repeated failures
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestAccountLockout:
    async def test_successful_login_resets_failed_count(self, client, db_session) -> None:
        email = "lockout-reset@example.com"
        await _register(client, email)
        await _login(client, email, "wrong")
        await _login(client, email, "wrong")

        resp = await _login(client, email, _PASSWORD)
        assert resp.status_code == 200

        result = await db_session.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        assert user.failed_login_count == 0
        assert user.locked_until is None

    async def test_unknown_email_never_locks_or_errors(self, client) -> None:
        settings = get_settings()
        email = "lockout-ghost@example.com"
        for _ in range(settings.lockout_max_attempts + 2):
            resp = await _login(client, email, "wrong")
            assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Access-token revocation: logout blacklist + password-change invalidation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestAccessTokenBlacklist:
    async def test_blacklisted_access_token_returns_401_on_me(self, client) -> None:
        email = "blacklist-logout@example.com"
        await _register(client, email)
        login_resp = await _login(client, email)
        tokens = login_resp.json()

        logout_resp = await client.post("/api/v1/auth/logout", headers=_auth(tokens["access_token"]))
        assert logout_resp.status_code == 204

        assert (await _me(client, tokens["access_token"])).status_code == 401

    async def test_unrelated_session_unaffected_by_logout(self, client) -> None:
        email = "blacklist-multisession@example.com"
        await _register(client, email)
        session_a = (await _login(client, email)).json()
        session_b = (await _login(client, email)).json()

        await client.post("/api/v1/auth/logout", headers=_auth(session_a["access_token"]))

        resp = await _me(client, session_b["access_token"])
        assert resp.status_code == 200

    async def test_logout_without_authorization_header_still_revokes_refresh(self, client) -> None:
        """No access token presented (e.g. client only kept the refresh
        cookie) must not block the refresh-token revocation."""
        email = "blacklist-no-header@example.com"
        await _register(client, email)
        await _login(client, email)

        logout_resp = await client.post("/api/v1/auth/logout")
        assert logout_resp.status_code == 204

        replay = await client.post("/api/v1/auth/refresh")
        assert replay.status_code == 401

    async def test_password_change_invalidates_prior_access_token(self, client) -> None:
        email = "blacklist-pwchange@example.com"
        await _register(client, email)
        old_token = (await _login(client, email)).json()["access_token"]

        change_resp = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": _PASSWORD, "new_password": "NewStrongPassw0rd!"},
            headers=_auth(old_token),
        )
        assert change_resp.status_code == 204

        assert (await _me(client, old_token)).status_code == 401

        # JWT `iat` is integer-second-granular: a token minted in the exact
        # same wall-clock second as the password change is ambiguous and
        # gets rejected too (see _invalidate_access_tokens_issued_before) —
        # sleep past the second boundary so this re-login lands unambiguously
        # *after* it, matching realistic human-paced usage.
        await asyncio.sleep(1.05)
        new_login = await _login(client, email, "NewStrongPassw0rd!")
        assert new_login.status_code == 200
        new_token = new_login.json()["access_token"]
        assert (await _me(client, new_token)).status_code == 200

    async def test_password_reset_invalidates_prior_access_token(self, client, monkeypatch) -> None:
        from app.core.config import get_settings as _get_settings

        monkeypatch.setenv("DEBUG", "true")
        _get_settings.cache_clear()

        email = "blacklist-pwreset@example.com"
        await _register(client, email)
        old_token = (await _login(client, email)).json()["access_token"]

        forgot_resp = await client.post("/api/v1/auth/forgot-password", json={"email": email})
        assert forgot_resp.status_code == 200
        raw_token = forgot_resp.json()["reset_token"]
        assert raw_token is not None

        reset_resp = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": raw_token, "new_password": "NewStrongPassw0rd!"},
        )
        assert reset_resp.status_code == 204

        assert (await _me(client, old_token)).status_code == 401

        _get_settings.cache_clear()

    async def test_revocation_enforced_on_a_standalone_app(self, client, app) -> None:
        """Same revocation check, exercised against a minimal app that only
        wires up get_current_user — confirms the blacklist check isn't
        somehow specific to the production router wiring."""
        from app.core.token_blacklist import get_token_blacklist
        from app.modules.auth.dependencies import get_async_db

        email = "blacklist-standalone@example.com"
        await _register(client, email)
        token = (await _login(client, email)).json()["access_token"]

        # Reuse the *same* in-memory blacklist + test-db overrides the main
        # `client` fixture's app is using, so logging out through `client`
        # is visible to this separate bare app's checks, and it reads the
        # same in-memory SQLite DB rather than the real Postgres.
        bare_app = _build_bare_protected_app(
            token_blacklist_override=app.dependency_overrides[get_token_blacklist],
            async_db_override=app.dependency_overrides[get_async_db],
        )
        transport = ASGITransport(app=bare_app)
        async with AsyncClient(transport=transport, base_url="https://test") as bare_client:
            ok = await bare_client.get("/protected", headers=_auth(token))
            assert ok.status_code == 200

        await client.post("/api/v1/auth/logout", headers=_auth(token))

        async with AsyncClient(transport=transport, base_url="https://test") as bare_client:
            blocked = await bare_client.get("/protected", headers=_auth(token))
            assert blocked.status_code == 401


# ---------------------------------------------------------------------------
# Token blacklist — unit level
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestTokenBlacklistUnit:
    async def test_jti_round_trip_and_expiry(self, monkeypatch) -> None:
        blacklist = InMemoryTokenBlacklist()
        clock = {"t": 0.0}
        monkeypatch.setattr("app.core.token_blacklist.time.monotonic", lambda: clock["t"])

        await blacklist.add_jti("abc", ttl_seconds=10)
        assert await blacklist.contains_jti("abc") is True
        clock["t"] = 11.0
        assert await blacklist.contains_jti("abc") is False

    async def test_invalidate_before_round_trip_and_expiry(self, monkeypatch) -> None:
        blacklist = InMemoryTokenBlacklist()
        clock = {"t": 0.0}
        monkeypatch.setattr("app.core.token_blacklist.time.monotonic", lambda: clock["t"])

        await blacklist.set_invalidate_before("user-1", timestamp=100.0, ttl_seconds=10)
        assert await blacklist.get_invalidate_before("user-1") == 100.0
        clock["t"] = 11.0
        assert await blacklist.get_invalidate_before("user-1") is None

    async def test_redis_construction_failure_falls_back_to_in_memory(self, monkeypatch) -> None:
        monkeypatch.setattr(get_settings(), "redis_url", "not a valid redis url")
        assert isinstance(get_token_blacklist(), InMemoryTokenBlacklist)

    async def test_redis_url_configured_builds_redis_backend(self, monkeypatch) -> None:
        monkeypatch.setattr(get_settings(), "redis_url", "redis://localhost:6379/0")
        assert isinstance(get_token_blacklist(), RedisTokenBlacklist)


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestSecurityHeaders:
    async def test_headers_present_on_health_check(self, client) -> None:
        resp = await client.get("/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    async def test_headers_present_on_404(self, client) -> None:
        resp = await client.get("/api/v1/this-route-does-not-exist")
        assert resp.status_code == 404
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    async def test_hsts_present_when_cookie_secure_true(self, client, monkeypatch) -> None:
        monkeypatch.setattr(get_settings(), "cookie_secure", True)
        resp = await client.get("/health")
        assert "Strict-Transport-Security" in resp.headers

    async def test_hsts_absent_when_cookie_secure_false(self, client, monkeypatch) -> None:
        monkeypatch.setattr(get_settings(), "cookie_secure", False)
        resp = await client.get("/health")
        assert "Strict-Transport-Security" not in resp.headers


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestCors:
    async def test_preflight_allows_configured_origin(self, client) -> None:
        origin = get_settings().cors_allow_origins[0]
        resp = await client.options(
            "/api/v1/auth/login",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == origin

    async def test_preflight_rejects_unlisted_origin(self, client) -> None:
        resp = await client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.headers.get("access-control-allow-origin") != "https://evil.example.com"
