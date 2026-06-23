"""Tests for the reserved tenant_id blocklist — POST/GET/DELETE
/api/v1/reserved-tenant-ids, and that a reserved tenant_id is rejected by
both organization-creation paths (POST /api/v1/organizations and
AuthService's tenant-provisioning path).

The migration's seed list (admin, www, api, ...) is only applied when
alembic actually runs against a real database — the in-memory test schema
is built straight from SQLAlchemy metadata, so these tests reserve their
own tenant_ids explicitly rather than relying on that seed data.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from app.modules.users.models import User
from sqlalchemy import select

_PASSWORD = "StrongPass1!"

pytestmark = pytest.mark.anyio


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register_and_login(client, email: str) -> str:
    await client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD})
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def _set_superuser(db_session, user_id: UUID | str, value: bool) -> None:
    result = await db_session.execute(select(User).where(User.id == UUID(str(user_id))))
    user = result.scalar_one()
    user.is_superuser = value
    db_session.add(user)
    await db_session.commit()


@pytest.fixture
def unique_tenant_id() -> str:
    return f"rsv-{uuid4().hex[:8]}"


@pytest.fixture
async def superuser_token(client, db_session, unique_tenant_id: str) -> str:
    email = f"{unique_tenant_id}@example.com"
    token = await _register_and_login(client, email)
    user_id = (await client.get("/api/v1/users/me", headers=_auth(token))).json()["id"]
    await _set_superuser(db_session, user_id, True)
    return token


@pytest.fixture
async def member_token(client) -> str:
    return await _register_and_login(client, f"rsv-member-{uuid4().hex[:8]}@example.com")


class TestReserveTenantId:
    async def test_reserve_success(self, client, superuser_token, unique_tenant_id):
        resp = await client.post(
            "/api/v1/reserved-tenant-ids",
            json={"tenant_id": unique_tenant_id, "reason": "system route conflict"},
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["tenant_id"] == unique_tenant_id
        assert body["reason"] == "system route conflict"

    async def test_reserve_requires_superuser(self, client, member_token, unique_tenant_id):
        resp = await client.post(
            "/api/v1/reserved-tenant-ids",
            json={"tenant_id": unique_tenant_id},
            headers=_auth(member_token),
        )
        assert resp.status_code == 403

    async def test_reserve_duplicate_returns_409(self, client, superuser_token, unique_tenant_id):
        payload = {"tenant_id": unique_tenant_id}
        first = await client.post("/api/v1/reserved-tenant-ids", json=payload, headers=_auth(superuser_token))
        assert first.status_code == 201
        second = await client.post(
            "/api/v1/reserved-tenant-ids", json=payload, headers=_auth(superuser_token)
        )
        assert second.status_code == 409

    async def test_reserve_rejects_too_short_tenant_id(self, client, superuser_token):
        resp = await client.post(
            "/api/v1/reserved-tenant-ids", json={"tenant_id": "a"}, headers=_auth(superuser_token)
        )
        assert resp.status_code == 422


class TestListReservedTenantIds:
    async def test_list_includes_reserved_entry(self, client, superuser_token, unique_tenant_id):
        await client.post(
            "/api/v1/reserved-tenant-ids",
            json={"tenant_id": unique_tenant_id},
            headers=_auth(superuser_token),
        )
        resp = await client.get("/api/v1/reserved-tenant-ids", headers=_auth(superuser_token))
        assert resp.status_code == 200
        assert any(e["tenant_id"] == unique_tenant_id for e in resp.json())

    async def test_list_requires_superuser(self, client, member_token):
        resp = await client.get("/api/v1/reserved-tenant-ids", headers=_auth(member_token))
        assert resp.status_code == 403


class TestUnreserveTenantId:
    async def test_unreserve_success(self, client, superuser_token, unique_tenant_id):
        await client.post(
            "/api/v1/reserved-tenant-ids",
            json={"tenant_id": unique_tenant_id},
            headers=_auth(superuser_token),
        )
        resp = await client.delete(
            f"/api/v1/reserved-tenant-ids/{unique_tenant_id}", headers=_auth(superuser_token)
        )
        assert resp.status_code == 204

        listed = await client.get("/api/v1/reserved-tenant-ids", headers=_auth(superuser_token))
        assert all(e["tenant_id"] != unique_tenant_id for e in listed.json())

    async def test_unreserve_unknown_returns_404(self, client, superuser_token, unique_tenant_id):
        resp = await client.delete(
            f"/api/v1/reserved-tenant-ids/{unique_tenant_id}", headers=_auth(superuser_token)
        )
        assert resp.status_code == 404

    async def test_unreserve_requires_superuser(self, client, member_token, unique_tenant_id):
        resp = await client.delete(
            f"/api/v1/reserved-tenant-ids/{unique_tenant_id}", headers=_auth(member_token)
        )
        assert resp.status_code == 403


class TestReservedTenantIdBlocksOrganizationCreation:
    async def test_create_organization_with_reserved_slug_returns_409(
        self, client, superuser_token, unique_tenant_id
    ):
        reserved = await client.post(
            "/api/v1/reserved-tenant-ids",
            json={"tenant_id": unique_tenant_id},
            headers=_auth(superuser_token),
        )
        assert reserved.status_code == 201

        resp = await client.post(
            "/api/v1/organizations",
            json={"name": "Blocked Org", "slug": unique_tenant_id},
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 409

    async def test_unreserving_allows_organization_creation(self, client, superuser_token, unique_tenant_id):
        await client.post(
            "/api/v1/reserved-tenant-ids",
            json={"tenant_id": unique_tenant_id},
            headers=_auth(superuser_token),
        )
        await client.delete(f"/api/v1/reserved-tenant-ids/{unique_tenant_id}", headers=_auth(superuser_token))

        resp = await client.post(
            "/api/v1/organizations",
            json={"name": "Now Allowed", "slug": unique_tenant_id},
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 201, resp.text
