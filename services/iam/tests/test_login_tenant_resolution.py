"""Tenant resolution at /login: single-org auto-select, multi-org 409,
explicit tenant_id selection/rejection, and the response/JWT shape that
carries tenant_id + role for downstream RBAC/ABAC evaluation.
"""

from __future__ import annotations

from uuid import UUID

import jwt
import pytest
from app.infrastructure.db.models.user import User
from sqlalchemy import select


async def _register(client, email: str, password: str = "Password123!") -> dict:
    resp = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _login(client, email: str, password: str = "Password123!", **kwargs):
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password, **kwargs})


async def _login_token(client, email: str, password: str = "Password123!") -> str:
    resp = await _login(client, email, password)
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


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


def _unverified_claims(access_token: str) -> dict:
    return jwt.decode(access_token, options={"verify_signature": False})


class TestNoOrganization:
    @pytest.mark.anyio
    async def test_login_with_no_org_has_null_tenant_and_role(self, client):
        await _register(client, "solo@test.com")
        resp = await _login(client, "solo@test.com")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["user"]["tenant"] is None
        assert body["user"]["role"] is None
        assert body["user"]["permissions"] == []

        claims = _unverified_claims(body["access_token"])
        assert "tenant_id" not in claims
        assert "role" not in claims


class TestSingleOrganization:
    @pytest.mark.anyio
    async def test_login_auto_selects_the_only_membership(self, client, db_session):
        await _register(client, "owner-solo@test.com")
        owner_token = await _login_token(client, "owner-solo@test.com")
        org = await _create_org(client, db_session, owner_token, name="Solo Org", slug="solo-org")

        resp = await _login(client, "owner-solo@test.com")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["user"]["tenant"] == {
            "id": org["id"],
            "tenant_id": "solo-org",
            "name": "Solo Org",
        }
        assert body["user"]["role"]["name"] == "Owner"

        claims = _unverified_claims(body["access_token"])
        assert claims["tenant_id"] == "solo-org"
        assert claims["role"] == "Owner"

    @pytest.mark.anyio
    async def test_session_and_links_are_populated(self, client):
        await _register(client, "shape@test.com")
        resp = await _login(client, "shape@test.com")
        body = resp.json()

        assert body["session"]["session_id"].startswith("sess_")
        assert body["session"]["device"]
        assert body["session"]["issued_at"]
        assert body["session"]["expires_at"]
        assert body["session"]["last_login"] is None  # first-ever login

        assert body["links"]["refresh"] == "/api/v1/auth/refresh"
        assert body["links"]["logout"] == "/api/v1/auth/logout"
        assert body["links"]["profile"] == f"/api/v1/users/{body['user']['id']}"

        # A second login now has a previous last_login to report.
        second = await _login(client, "shape@test.com")
        assert second.json()["session"]["last_login"] is not None


class TestMultipleOrganizations:
    @pytest.mark.anyio
    async def test_login_without_tenant_id_returns_409_with_org_list(self, client, db_session):
        await _register(client, "multi@test.com")
        token = await _login_token(client, "multi@test.com")
        await _create_org(client, db_session, token, name="Org A", slug="org-a")

        await _register(client, "owner-b@test.com")
        owner_b_token = await _login_token(client, "owner-b@test.com")
        org_b = await _create_org(client, db_session, owner_b_token, name="Org B", slug="org-b")
        add_resp = await client.post(
            f"/api/v1/organizations/{org_b['id']}/members",
            json={
                "user_id": (await _whoami(client, token))["id"],
                "role_code": "member",
            },
            headers=_auth(owner_b_token),
        )
        assert add_resp.status_code == 201, add_resp.text

        resp = await _login(client, "multi@test.com")
        assert resp.status_code == 409, resp.text
        orgs = resp.json()["organizations"]
        assert {o["tenant_id"] for o in orgs} == {"org-a", "org-b"}

    @pytest.mark.anyio
    async def test_login_with_explicit_tenant_id_selects_that_org(self, client, db_session):
        await _register(client, "multi2@test.com")
        token = await _login_token(client, "multi2@test.com")
        await _create_org(client, db_session, token, name="Org A2", slug="org-a2")

        await _register(client, "owner-b2@test.com")
        owner_b_token = await _login_token(client, "owner-b2@test.com")
        org_b = await _create_org(client, db_session, owner_b_token, name="Org B2", slug="org-b2")
        await client.post(
            f"/api/v1/organizations/{org_b['id']}/members",
            json={
                "user_id": (await _whoami(client, token))["id"],
                "role_code": "member",
            },
            headers=_auth(owner_b_token),
        )

        resp = await _login(client, "multi2@test.com", tenant_id=org_b["slug"])
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["user"]["tenant"]["tenant_id"] == "org-b2"
        assert body["user"]["role"]["name"] == "Member"

    @pytest.mark.anyio
    async def test_login_with_tenant_id_not_a_member_of_returns_403(self, client, db_session):
        await _register(client, "outsider3@test.com")

        await _register(client, "owner3@test.com")
        owner_token = await _login_token(client, "owner3@test.com")
        org = await _create_org(client, db_session, owner_token, name="Org C", slug="org-c")

        resp = await _login(client, "outsider3@test.com", tenant_id=org["slug"])
        assert resp.status_code == 403, resp.text


async def _whoami(client, token: str) -> dict:
    resp = await client.get("/api/v1/users/me", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()
