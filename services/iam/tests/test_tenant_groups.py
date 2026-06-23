"""HTTP tests for the new Tenant entity and its many-to-many link to
Organization (POST/GET/PATCH/DELETE /tenant-groups, .../organizations) —
see app/api/v1/routes/tenant_groups.py and app/services/tenant_service.py.

Distinct from /tenants (the pre-existing organization-bootstrap API where
"tenant_id" means Organization.slug, exercised in test_admin_provisioning.py
etc.) — unaffected by this.
"""

from __future__ import annotations

from uuid import UUID, uuid4

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


async def _create_org(client, token: str, *, slug: str, name: str = "Acme Inc") -> dict:
    resp = await client.post("/api/v1/organizations", json={"name": name, "slug": slug}, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_tenant_group(client, token: str, *, slug: str, name: str = "Acme Group") -> dict:
    resp = await client.post("/api/v1/tenant-groups", json={"name": name, "slug": slug}, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def admin_token(client, db_session):
    await _register(client, "tg-admin@test.com")
    token = await _login_token(client, "tg-admin@test.com")
    user_id = (await client.get("/api/v1/users/me", headers=_auth(token))).json()["id"]
    await _make_superuser(db_session, user_id)
    return token


@pytest.fixture
async def regular_token(client):
    await _register(client, "tg-regular@test.com")
    return await _login_token(client, "tg-regular@test.com")


class TestTenantGroupLifecycle:
    async def test_create_requires_superuser(self, client, regular_token):
        resp = await client.post(
            "/api/v1/tenant-groups",
            json={"name": "Acme Group", "slug": "acme-group-1"},
            headers=_auth(regular_token),
        )
        assert resp.status_code == 403

    async def test_create_get_list_update_delete(self, client, admin_token):
        tenant_group = await _create_tenant_group(client, admin_token, slug="acme-group-2")
        assert tenant_group["is_active"] is True

        get_resp = await client.get(f"/api/v1/tenant-groups/{tenant_group['id']}", headers=_auth(admin_token))
        assert get_resp.status_code == 200
        assert get_resp.json()["slug"] == "acme-group-2"

        list_resp = await client.get("/api/v1/tenant-groups", headers=_auth(admin_token))
        assert list_resp.status_code == 200
        assert any(t["id"] == tenant_group["id"] for t in list_resp.json())

        update_resp = await client.patch(
            f"/api/v1/tenant-groups/{tenant_group['id']}",
            json={"name": "Renamed", "is_active": False},
            headers=_auth(admin_token),
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["name"] == "Renamed"
        assert update_resp.json()["is_active"] is False

        delete_resp = await client.delete(
            f"/api/v1/tenant-groups/{tenant_group['id']}", headers=_auth(admin_token)
        )
        assert delete_resp.status_code == 204

        missing_resp = await client.get(
            f"/api/v1/tenant-groups/{tenant_group['id']}", headers=_auth(admin_token)
        )
        assert missing_resp.status_code == 404

    async def test_duplicate_slug_rejected(self, client, admin_token):
        await _create_tenant_group(client, admin_token, slug="dupe-tenant-group")
        second = await client.post(
            "/api/v1/tenant-groups",
            json={"name": "Dup", "slug": "dupe-tenant-group"},
            headers=_auth(admin_token),
        )
        assert second.status_code == 409

    async def test_get_missing_returns_404(self, client, admin_token):
        resp = await client.get(f"/api/v1/tenant-groups/{uuid4()}", headers=_auth(admin_token))
        assert resp.status_code == 404


class TestTenantGroupOrganizationMembership:
    async def test_link_list_and_unlink_organization(self, client, admin_token):
        tenant_group = await _create_tenant_group(client, admin_token, slug="membership-group")
        org = await _create_org(client, admin_token, slug="tg-member-org")

        link_resp = await client.post(
            f"/api/v1/tenant-groups/{tenant_group['id']}/organizations",
            json={"organization_id": org["id"]},
            headers=_auth(admin_token),
        )
        assert link_resp.status_code == 201, link_resp.text
        assert link_resp.json()["id"] == org["id"]

        list_resp = await client.get(
            f"/api/v1/tenant-groups/{tenant_group['id']}/organizations", headers=_auth(admin_token)
        )
        assert list_resp.status_code == 200
        assert [o["id"] for o in list_resp.json()] == [org["id"]]

        reverse_resp = await client.get(
            f"/api/v1/tenant-groups/by-organization/{org['id']}", headers=_auth(admin_token)
        )
        assert reverse_resp.status_code == 200
        assert [t["id"] for t in reverse_resp.json()] == [tenant_group["id"]]

        duplicate_link = await client.post(
            f"/api/v1/tenant-groups/{tenant_group['id']}/organizations",
            json={"organization_id": org["id"]},
            headers=_auth(admin_token),
        )
        assert duplicate_link.status_code == 409

        unlink_resp = await client.delete(
            f"/api/v1/tenant-groups/{tenant_group['id']}/organizations/{org['id']}",
            headers=_auth(admin_token),
        )
        assert unlink_resp.status_code == 204

        after_unlink = await client.get(
            f"/api/v1/tenant-groups/{tenant_group['id']}/organizations", headers=_auth(admin_token)
        )
        assert after_unlink.json() == []

        unlink_again = await client.delete(
            f"/api/v1/tenant-groups/{tenant_group['id']}/organizations/{org['id']}",
            headers=_auth(admin_token),
        )
        assert unlink_again.status_code == 404

    async def test_link_unknown_organization_returns_404(self, client, admin_token):
        tenant_group = await _create_tenant_group(client, admin_token, slug="lonely-group")

        resp = await client.post(
            f"/api/v1/tenant-groups/{tenant_group['id']}/organizations",
            json={"organization_id": str(uuid4())},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 404

    async def test_link_unknown_tenant_group_returns_404(self, client, admin_token):
        org = await _create_org(client, admin_token, slug="tg-orphan-org")

        resp = await client.post(
            f"/api/v1/tenant-groups/{uuid4()}/organizations",
            json={"organization_id": org["id"]},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 404

    async def test_organization_can_join_multiple_tenant_groups(self, client, admin_token):
        org = await _create_org(client, admin_token, slug="tg-multi-org")
        tenant_group_a = await _create_tenant_group(client, admin_token, name="Group A", slug="group-a")
        tenant_group_b = await _create_tenant_group(client, admin_token, name="Group B", slug="group-b")

        for tenant_group in (tenant_group_a, tenant_group_b):
            resp = await client.post(
                f"/api/v1/tenant-groups/{tenant_group['id']}/organizations",
                json={"organization_id": org["id"]},
                headers=_auth(admin_token),
            )
            assert resp.status_code == 201

        reverse_resp = await client.get(
            f"/api/v1/tenant-groups/by-organization/{org['id']}", headers=_auth(admin_token)
        )
        assert {t["id"] for t in reverse_resp.json()} == {tenant_group_a["id"], tenant_group_b["id"]}

    async def test_tenant_group_can_have_multiple_organizations(self, client, admin_token):
        tenant_group = await _create_tenant_group(client, admin_token, slug="shared-group")
        org_a = await _create_org(client, admin_token, name="Org A", slug="shared-org-a")
        org_b = await _create_org(client, admin_token, name="Org B", slug="shared-org-b")

        for org in (org_a, org_b):
            resp = await client.post(
                f"/api/v1/tenant-groups/{tenant_group['id']}/organizations",
                json={"organization_id": org["id"]},
                headers=_auth(admin_token),
            )
            assert resp.status_code == 201

        list_resp = await client.get(
            f"/api/v1/tenant-groups/{tenant_group['id']}/organizations", headers=_auth(admin_token)
        )
        assert {o["id"] for o in list_resp.json()} == {org_a["id"], org_b["id"]}
