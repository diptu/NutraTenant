"""POST /api/v1/users — admin user provisioning that returns the Common
User Object (UserProfileOut), distinct from POST /admin/users' narrower
{user_id, status, temp_password_sent} contract (see test_admin_provisioning.py).
Both share the same underlying AuthService.provision_user flow.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from app.modules.users.models import User
from sqlalchemy import select

pytestmark = pytest.mark.anyio


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str, password: str = "Password123!") -> dict:
    resp = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _login_token(client, email: str, password: str = "Password123!") -> str:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _make_superuser(db_session, user_id: str) -> None:
    result = await db_session.execute(select(User).where(User.id == UUID(str(user_id))))
    user = result.scalar_one()
    user.is_superuser = True
    db_session.add(user)
    await db_session.commit()


async def _superuser_token(client, db_session, email: str) -> str:
    await _register(client, email)
    token = await _login_token(client, email)
    user_id = (await client.get("/api/v1/users/me", headers=_auth(token))).json()["id"]
    await _make_superuser(db_session, user_id)
    return await _login_token(client, email)


async def _create_org(client, token: str, *, name: str, slug: str) -> dict:
    resp = await client.post("/api/v1/organizations", json={"name": name, "slug": slug}, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestCreateUser:
    async def test_superuser_creates_user_returns_common_user_object(self, client, db_session):
        super_token = await _superuser_token(client, db_session, "root-up@test.com")
        await _create_org(client, super_token, name="Apple Corp", slug="apple-corp-up")

        resp = await client.post(
            "/api/v1/users",
            json={
                "name": "Jane Smith",
                "email": "jane@applecorp.com",
                "username": "janesmith",
                "phone": "+8801711122233",
                "tenant_id": "apple-corp-up",
                "role": "MEMBER",
                "attributes": {
                    "department": "Engineering",
                    "designation": "Developer",
                    "location": "Dhaka",
                },
            },
            headers=_auth(super_token),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()

        assert body["name"] == "Jane Smith"
        assert body["email"] == "jane@applecorp.com"
        assert body["username"] == "janesmith"
        assert body["phone"] == "+8801711122233"
        assert body["status"] == "ACTIVE"
        assert body["email_verified"] is False
        assert body["mfa_enabled"] is False
        assert body["tenant"] == {
            "id": body["tenant"]["id"],
            "tenant_id": "apple-corp-up",
            "name": "Apple Corp",
        }
        assert body["role"]["name"] == "Member"
        assert body["permissions"] == []
        assert body["attributes"] == {
            "department": "Engineering",
            "designation": "Developer",
            "location": "Dhaka",
        }

        result = await db_session.execute(select(User).where(User.id == UUID(body["id"])))
        user = result.scalar_one()
        assert user.must_change_password is True
        assert user.password_hash is not None

    async def test_attributes_merge_over_org_defaults_without_overwriting(self, client, db_session):
        super_token = await _superuser_token(client, db_session, "root-up2@test.com")
        org = await _create_org(client, super_token, name="Acme", slug="acme-up-defaults")
        await client.patch(
            f"/api/v1/organizations/{org['id']}",
            json={"default_attributes": {"region": "EU", "department": "Unassigned"}},
            headers=_auth(super_token),
        )

        resp = await client.post(
            "/api/v1/users",
            json={
                "email": "merged@test.com",
                "tenant_id": "acme-up-defaults",
                "role": "Member",
                "attributes": {"department": "Engineering"},
            },
            headers=_auth(super_token),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["attributes"] == {"region": "EU", "department": "Engineering"}

    async def test_non_superuser_is_forbidden(self, client, db_session):
        super_token = await _superuser_token(client, db_session, "root-up7@test.com")
        await _create_org(client, super_token, name="BB", slug="tenant-b-up")
        regular_token = await _login_token(client, (await _register(client, "regular-up@test.com"))["email"])

        resp = await client.post(
            "/api/v1/users",
            json={"email": "x-up@test.com", "tenant_id": "tenant-b-up", "role": "Member"},
            headers=_auth(regular_token),
        )
        assert resp.status_code == 403, resp.text

    async def test_unknown_tenant_returns_404(self, client, db_session):
        super_token = await _superuser_token(client, db_session, "root-up3@test.com")
        resp = await client.post(
            "/api/v1/users",
            json={"email": "x2-up@test.com", "tenant_id": "no-such-tenant-up", "role": "Member"},
            headers=_auth(super_token),
        )
        assert resp.status_code == 404, resp.text

    async def test_unknown_role_returns_404(self, client, db_session):
        super_token = await _superuser_token(client, db_session, "root-up4@test.com")
        await _create_org(client, super_token, name="CC", slug="tenant-c-up")

        resp = await client.post(
            "/api/v1/users",
            json={"email": "x3-up@test.com", "tenant_id": "tenant-c-up", "role": "NotARole"},
            headers=_auth(super_token),
        )
        assert resp.status_code == 404, resp.text

    async def test_duplicate_email_returns_409(self, client, db_session):
        super_token = await _superuser_token(client, db_session, "root-up5@test.com")
        await _create_org(client, super_token, name="DD", slug="tenant-d-up")
        await _register(client, "dup-up@test.com")

        resp = await client.post(
            "/api/v1/users",
            json={"email": "dup-up@test.com", "tenant_id": "tenant-d-up", "role": "Member"},
            headers=_auth(super_token),
        )
        assert resp.status_code == 409, resp.text

    async def test_duplicate_username_returns_409(self, client, db_session):
        super_token = await _superuser_token(client, db_session, "root-up6@test.com")
        await _create_org(client, super_token, name="EE", slug="tenant-e-up")

        first = await client.post(
            "/api/v1/users",
            json={
                "email": "first-up@test.com",
                "username": "shared-handle",
                "tenant_id": "tenant-e-up",
                "role": "Member",
            },
            headers=_auth(super_token),
        )
        assert first.status_code == 201, first.text

        second = await client.post(
            "/api/v1/users",
            json={
                "email": "second-up@test.com",
                "username": "shared-handle",
                "tenant_id": "tenant-e-up",
                "role": "Member",
            },
            headers=_auth(super_token),
        )
        assert second.status_code == 409, second.text

    async def test_unauthenticated_is_rejected(self, client):
        resp = await client.post(
            "/api/v1/users",
            json={"email": "x-up@test.com", "tenant_id": "anything", "role": "Member"},
        )
        assert resp.status_code == 401
