"""Contextual tenant switching: POST /api/v1/auth/switch-tenant."""

from __future__ import annotations

from uuid import UUID

import pytest
from app.modules.users.models import User
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select


@pytest.fixture
async def https_client(app):
    """https:// (not conftest's http://) so httpx actually honours the
    refresh cookie's `Secure` flag on outgoing requests — needed only by
    the rotation-continuity test below, which round-trips the cookie
    through a second request. Same pattern as test_auth_federation.py's
    `client_ctx`.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as ac:
        yield ac


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str, password: str = "Password123!") -> dict:
    resp = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _login(client, email: str, password: str = "Password123!", **kwargs) -> dict:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password, **kwargs})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _set_superuser(db_session, user_id: UUID | str, value: bool) -> None:
    result = await db_session.execute(select(User).where(User.id == UUID(str(user_id))))
    user = result.scalar_one()
    user.is_superuser = value
    db_session.add(user)
    await db_session.commit()


async def _create_org(client, db_session, token: str, *, name: str, slug: str) -> dict:
    """Organization/tenant creation is superuser-only — transiently promotes
    the acting token's user, then demotes them back so the rest of the test
    still exercises regular non-superuser behavior."""
    user_id = (await client.get("/api/v1/users/me", headers=_auth(token))).json()["id"]
    await _set_superuser(db_session, user_id, True)
    resp = await client.post("/api/v1/organizations", json={"name": name, "slug": slug}, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    await _set_superuser(db_session, user_id, False)
    return resp.json()


class TestSwitchTenant:
    @pytest.mark.anyio
    async def test_switch_to_a_membership_reissues_claims(self, client, db_session):
        email = (await _register(client, "multi@test.com"))["email"]
        first_login = await _login(client, email)
        await _create_org(client, db_session, first_login["access_token"], name="AA", slug="switch-a")

        # Get a second org via another owner, then add this user as a member.
        other_owner = (await _register(client, "otherowner@test.com"))["email"]
        other_token = (await _login(client, other_owner))["access_token"]
        org_b = await _create_org(client, db_session, other_token, name="BB", slug="switch-b")
        user_id = (await client.get("/api/v1/users/me", headers=_auth(first_login["access_token"]))).json()[
            "id"
        ]
        await client.post(
            f"/api/v1/organizations/{org_b['id']}/members",
            json={"user_id": user_id, "role_code": "member"},
            headers=_auth(other_token),
        )

        # Log in scoped to org A (re-login: org A didn't exist at first_login time).
        scoped_a = await _login(client, email, tenant_id="switch-a")

        resp = await client.post(
            "/api/v1/auth/switch-tenant",
            json={"tenant_id": "switch-b"},
            headers=_auth(scoped_a["access_token"]),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body.keys()) == {"access_token"}

        # Tenant/role context isn't embedded in the access token itself —
        # it's resolved dynamically per-request from the session the new
        # token's session_id points at (see
        # app.modules.auth.dependencies.get_current_tenant_slug), so
        # confirm the switch took effect via GET /users/me instead of
        # decoding the JWT.
        me = await client.get("/api/v1/users/me", headers=_auth(body["access_token"]))
        assert me.status_code == 200, me.text
        assert me.json()["tenant"]["tenant_id"] == "switch-b"
        assert me.json()["role"]["name"] == "Member"

    @pytest.mark.anyio
    async def test_switch_to_non_member_tenant_returns_403(self, client, db_session):
        email = (await _register(client, "soloperson@test.com"))["email"]
        login = await _login(client, email)

        other_owner = (await _register(client, "otherowner2@test.com"))["email"]
        other_token = (await _login(client, other_owner))["access_token"]
        await _create_org(client, db_session, other_token, name="CC", slug="switch-c")

        resp = await client.post(
            "/api/v1/auth/switch-tenant",
            json={"tenant_id": "switch-c"},
            headers=_auth(login["access_token"]),
        )
        assert resp.status_code == 403, resp.text

    @pytest.mark.anyio
    async def test_switch_to_unknown_tenant_returns_404(self, client):
        email = (await _register(client, "soloperson2@test.com"))["email"]
        login = await _login(client, email)

        resp = await client.post(
            "/api/v1/auth/switch-tenant",
            json={"tenant_id": "no-such-tenant-at-all"},
            headers=_auth(login["access_token"]),
        )
        assert resp.status_code == 404, resp.text

    @pytest.mark.anyio
    async def test_unauthenticated_switch_is_rejected(self, client):
        resp = await client.post("/api/v1/auth/switch-tenant", json={"tenant_id": "whatever"})
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_refresh_after_switch_keeps_new_tenant_context(self, https_client, db_session):
        """The whole point of rotating the refresh token on switch: a later
        silent /refresh must not revert to the tenant the original access
        token was minted under."""
        client = https_client
        email = (await _register(client, "rotator@test.com"))["email"]
        first_login = await _login(client, email)
        await _create_org(client, db_session, first_login["access_token"], name="DD", slug="switch-d")

        other_owner = (await _register(client, "otherowner3@test.com"))["email"]
        other_token = (await _login(client, other_owner))["access_token"]
        org_e = await _create_org(client, db_session, other_token, name="EE", slug="switch-e")
        user_id = (await client.get("/api/v1/users/me", headers=_auth(first_login["access_token"]))).json()[
            "id"
        ]
        await client.post(
            f"/api/v1/organizations/{org_e['id']}/members",
            json={"user_id": user_id, "role_code": "member"},
            headers=_auth(other_token),
        )

        scoped_d = await _login(client, email, tenant_id="switch-d")

        switch_resp = await client.post(
            "/api/v1/auth/switch-tenant",
            json={"tenant_id": "switch-e"},
            headers=_auth(scoped_d["access_token"]),
        )
        assert switch_resp.status_code == 200, switch_resp.text

        refresh_resp = await client.post("/api/v1/auth/refresh")
        assert refresh_resp.status_code == 200, refresh_resp.text
        me = await client.get(
            "/api/v1/users/me", headers=_auth(refresh_resp.json()["access_token"])
        )
        assert me.status_code == 200, me.text
        assert me.json()["tenant"]["tenant_id"] == "switch-e"
