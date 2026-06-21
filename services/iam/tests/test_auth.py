"""
Core authentication endpoint regression tests.

Updated to the current contract: JSON login (not OAuth2 form-encoded),
refresh tokens delivered only via an HttpOnly cookie (never in the JSON
body), and `/api/v1/users/me` rather than `/api/v1/auth/me`.

tests/test_auth_federation.py already covers refresh rotation/reuse
detection and logout exhaustively — this file sticks to registration/login
regression sanity and the OpenAPI security-scheme checks, which aren't
duplicated there.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

_BASE = "https://test"  # https so Secure cookies are honoured by httpx


@pytest.fixture
async def https_client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=_BASE) as ac:
        yield ac


@pytest.fixture
def unique_email() -> str:
    return f"test-{uuid4().hex[:8]}@example.com"


async def _register(client, email: str, password: str = "StrongPass1!"):
    return await client.post("/api/v1/auth/register", json={"email": email, "password": password})


async def _login(client, email: str, password: str = "StrongPass1!"):
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


# ===========================================================================
# REGRESSION: /register
# ===========================================================================


class TestRegisterRegression:
    @pytest.mark.anyio
    async def test_register_returns_201_with_user(self, https_client, unique_email):
        response = await _register(https_client, unique_email)
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == unique_email
        assert "id" in data
        assert "password_hash" not in data

    @pytest.mark.anyio
    async def test_register_duplicate_email_returns_409(self, https_client, unique_email):
        await _register(https_client, unique_email)
        response = await _register(https_client, unique_email)
        assert response.status_code == 409

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "payload",
        [
            {"password": "StrongPass1!"},
            {"email": "x@example.com"},
        ],
    )
    async def test_register_missing_fields_returns_422(self, https_client, payload):
        response = await https_client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 422


# ===========================================================================
# REGRESSION: /login
# ===========================================================================


class TestLoginRegression:
    @pytest.mark.anyio
    async def test_login_returns_access_token_and_refresh_cookie(self, https_client, unique_email):
        await _register(https_client, unique_email)
        response = await _login(https_client, unique_email)

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        # Set in both places: the httponly cookie (browser clients) and the
        # JSON body (non-browser clients with no cookie jar) — see
        # RefreshRequest in app/api/v1/schemas/auth.py.
        assert data["refresh_token"]
        assert data["token_type"].lower() == "bearer"
        assert "refresh_token" in response.cookies

    @pytest.mark.anyio
    async def test_login_wrong_password_returns_401(self, https_client, unique_email):
        await _register(https_client, unique_email)
        response = await _login(https_client, unique_email, "WrongPass999!")
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_login_unknown_email_returns_401(self, https_client):
        response = await _login(https_client, "ghost@nowhere.com")
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_login_missing_fields_returns_422(self, https_client):
        response = await https_client.post("/api/v1/auth/login", json={"email": "", "password": ""})
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_login_sets_httponly_secure_refresh_cookie(self, https_client, unique_email):
        await _register(https_client, unique_email)
        response = await _login(https_client, unique_email)

        set_cookie = response.headers.get("set-cookie", "")
        assert "refresh_token=" in set_cookie
        assert "httponly" in set_cookie.lower()
        assert "secure" in set_cookie.lower()


# ===========================================================================
# GET /users/me — protected profile endpoint
# ===========================================================================


class TestGetMe:
    @pytest.mark.anyio
    async def test_get_me_without_token_returns_401(self, https_client):
        response = await https_client.get("/api/v1/users/me")
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_get_me_with_access_token_returns_profile(self, https_client, unique_email):
        await _register(https_client, unique_email)
        login_resp = await _login(https_client, unique_email)
        access_token = login_resp.json()["access_token"]

        response = await https_client.get(
            "/api/v1/users/me", headers={"Authorization": f"Bearer {access_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == unique_email
        assert "id" in data
        assert "password_hash" not in data

    @pytest.mark.anyio
    async def test_get_me_with_invalid_token_returns_401(self, https_client):
        response = await https_client.get(
            "/api/v1/users/me", headers={"Authorization": "Bearer not.a.valid.jwt"}
        )
        assert response.status_code == 401


# ===========================================================================
# OPENAPI SCHEMA — security scheme registration
# ===========================================================================


class TestOpenApiSchema:
    @pytest.mark.anyio
    async def test_openapi_includes_bearer_security_scheme(self, https_client):
        """HTTPBearer must appear in securitySchemes for Swagger's Authorize
        button to work — current auth uses Bearer tokens, not OAuth2 password flow."""
        response = await https_client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        schemes = schema.get("components", {}).get("securitySchemes", {})
        assert schemes, "securitySchemes missing — Swagger Authorize button will not appear"
        assert any(s.get("scheme") == "bearer" for s in schemes.values())

    @pytest.mark.anyio
    async def test_me_endpoint_carries_security_lock(self, https_client):
        """GET /users/me must declare a security requirement (lock icon)."""
        response = await https_client.get("/openapi.json")
        schema = response.json()
        me_op = schema["paths"]["/api/v1/users/me"]["get"]
        assert me_op.get("security"), "Lock icon missing — no security requirement in OpenAPI spec"

    @pytest.mark.anyio
    async def test_login_endpoint_has_no_security_lock(self, https_client):
        """Login itself must be open — no security requirement on the token endpoint."""
        response = await https_client.get("/openapi.json")
        schema = response.json()
        login_op = schema["paths"]["/api/v1/auth/login"]["post"]
        assert not login_op.get("security"), "Login endpoint must remain open (no auth requirement)"
