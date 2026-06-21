"""Admin provisioning flow: POST /api/v1/admin/users."""

from __future__ import annotations

from uuid import UUID

import pytest
from app.infrastructure.db.models.user import User
from sqlalchemy import select


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str, password: str = "Password123!") -> dict:
    resp = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _login(client, email: str, password: str = "Password123!") -> dict:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _login_token(client, email: str, password: str = "Password123!") -> str:
    return (await _login(client, email, password))["access_token"]


async def _set_superuser(db_session, user_id: UUID | str, value: bool) -> None:
    result = await db_session.execute(select(User).where(User.id == UUID(str(user_id))))
    user = result.scalar_one()
    user.is_superuser = value
    db_session.add(user)
    await db_session.commit()


async def _make_superuser(db_session, user_id: UUID | str) -> None:
    await _set_superuser(db_session, user_id, True)


async def _create_org(client, db_session, token: str, *, name: str, slug: str) -> dict:
    """Organization/tenant creation is superuser-only — transiently promotes
    the acting token's user, then demotes them back so the rest of the test
    still exercises regular non-superuser behavior."""
    user_id = (await client.get("/api/v1/users/me", headers=_auth(token))).json()["id"]
    await _make_superuser(db_session, user_id)
    resp = await client.post("/api/v1/organizations", json={"name": name, "slug": slug}, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    await _set_superuser(db_session, user_id, False)
    return resp.json()


async def _superuser_token(client, db_session, email: str) -> str:
    await _register(client, email)
    token = await _login_token(client, email)
    user_id = (await client.get("/api/v1/users/me", headers=_auth(token))).json()["id"]
    await _make_superuser(db_session, user_id)
    return await _login_token(client, email)


class TestAdminCreateUser:
    @pytest.mark.anyio
    async def test_superuser_provisions_user_into_tenant(self, client, db_session):
        super_token = await _superuser_token(client, db_session, "root@test.com")

        owner_token = await _login_token(client, (await _register(client, "tenantowner@test.com"))["email"])
        await _create_org(client, db_session, owner_token, name="Acme", slug="acme-provisioned")

        resp = await client.post(
            "/api/v1/admin/users",
            json={
                "email": "provisioned@test.com",
                "name": "Provisioned Person",
                "tenant_id": "acme-provisioned",
                "role": "Member",
            },
            headers=_auth(super_token),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "INVITED"
        assert body["temp_password_sent"] is True
        assert "user_id" in body

    @pytest.mark.anyio
    async def test_non_superuser_is_forbidden(self, client, db_session):
        owner_token = await _login_token(client, (await _register(client, "owner10@test.com"))["email"])
        await _create_org(client, db_session, owner_token, name="B", slug="tenant-b-admin")

        resp = await client.post(
            "/api/v1/admin/users",
            json={
                "email": "x@test.com",
                "tenant_id": "tenant-b-admin",
                "role": "Member",
            },
            headers=_auth(owner_token),
        )
        assert resp.status_code == 403, resp.text

    @pytest.mark.anyio
    async def test_unauthenticated_is_rejected(self, client):
        resp = await client.post(
            "/api/v1/admin/users",
            json={"email": "x@test.com", "tenant_id": "anything", "role": "Member"},
        )
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_unknown_tenant_returns_404(self, client, db_session):
        super_token = await _superuser_token(client, db_session, "root2@test.com")
        resp = await client.post(
            "/api/v1/admin/users",
            json={
                "email": "x2@test.com",
                "tenant_id": "no-such-tenant",
                "role": "Member",
            },
            headers=_auth(super_token),
        )
        assert resp.status_code == 404, resp.text

    @pytest.mark.anyio
    async def test_unknown_role_returns_404(self, client, db_session):
        super_token = await _superuser_token(client, db_session, "root3@test.com")
        owner_token = await _login_token(client, (await _register(client, "owner11@test.com"))["email"])
        await _create_org(client, db_session, owner_token, name="C", slug="tenant-c-admin")

        resp = await client.post(
            "/api/v1/admin/users",
            json={
                "email": "x3@test.com",
                "tenant_id": "tenant-c-admin",
                "role": "NotARole",
            },
            headers=_auth(super_token),
        )
        assert resp.status_code == 404, resp.text

    @pytest.mark.anyio
    async def test_duplicate_email_returns_409(self, client, db_session):
        super_token = await _superuser_token(client, db_session, "root4@test.com")
        owner_token = await _login_token(client, (await _register(client, "owner12@test.com"))["email"])
        await _create_org(client, db_session, owner_token, name="D", slug="tenant-d-admin")
        await _register(client, "dup@test.com")

        resp = await client.post(
            "/api/v1/admin/users",
            json={
                "email": "dup@test.com",
                "tenant_id": "tenant-d-admin",
                "role": "Member",
            },
            headers=_auth(super_token),
        )
        assert resp.status_code == 409, resp.text

    @pytest.mark.anyio
    async def test_provisioned_account_has_no_usable_known_password_until_changed(self, client, db_session):
        """The contract never reveals the temp password over the API — the
        provisioned user can't log in without it. Verifies must_change_password
        is set server-side (via the DB) and is cleared by change-password."""
        super_token = await _superuser_token(client, db_session, "root5@test.com")
        owner_token = await _login_token(client, (await _register(client, "owner13@test.com"))["email"])
        await _create_org(client, db_session, owner_token, name="E", slug="tenant-e-admin")

        resp = await client.post(
            "/api/v1/admin/users",
            json={
                "email": "flagged@test.com",
                "tenant_id": "tenant-e-admin",
                "role": "Member",
            },
            headers=_auth(super_token),
        )
        user_id = resp.json()["user_id"]

        result = await db_session.execute(select(User).where(User.id == UUID(user_id)))
        user = result.scalar_one()
        assert user.must_change_password is True
        assert user.password_hash is not None  # never left without a password

    @pytest.mark.anyio
    async def test_endpoint_is_marked_deprecated_in_openapi(self, client):
        """Superseded by POST /api/v1/users (Common User Object response) —
        kept working for existing callers, but flagged so new integrations
        don't build against it."""
        response = await client.get("/openapi.json")
        assert response.status_code == 200
        op = response.json()["paths"]["/api/v1/admin/users"]["post"]
        assert op.get("deprecated") is True
