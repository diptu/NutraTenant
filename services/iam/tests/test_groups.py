"""Groups & Group Memberships API tests — POST/GET/PATCH/DELETE /api/v1/groups
and .../group-memberships (groups-group-memberships-api-spec).

This route was previously a stub with no endpoints, so there's no legacy
contract to preserve — every test below exercises the spec's contract
directly: tenant-scoped group CRUD with a parent hierarchy + ABAC attribute
bag, and membership CRUD with role/status/expiry.
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


async def _create_org(client, db_session, token: str, *, slug: str) -> dict:
    """Organization creation is superuser-only; the creator becomes that
    org's owner automatically — same helper pattern as test_rbac_tenancy.py."""
    user_id = (await client.get("/api/v1/users/me", headers=_auth(token))).json()["id"]
    await _set_superuser(db_session, user_id, True)
    resp = await client.post(
        "/api/v1/organizations", json={"name": "Acme Inc", "slug": slug}, headers=_auth(token)
    )
    assert resp.status_code == 201, resp.text
    await _set_superuser(db_session, user_id, False)
    return resp.json()


@pytest.fixture
def unique_slug() -> str:
    return f"grp-org-{uuid4().hex[:8]}"


@pytest.fixture
async def owner_token(client, unique_slug: str) -> str:
    return await _register_and_login(client, f"owner-{unique_slug}@example.com")


@pytest.fixture
async def org(client, db_session, owner_token: str, unique_slug: str) -> dict:
    return await _create_org(client, db_session, owner_token, slug=unique_slug)


@pytest.fixture
async def member_token(client, org: dict, owner_token: str, unique_slug: str) -> str:
    token = await _register_and_login(client, f"member-{unique_slug}@example.com")
    user_id = (await client.get("/api/v1/users/me", headers=_auth(token))).json()["id"]
    resp = await client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"user_id": user_id},
        headers=_auth(owner_token),
    )
    assert resp.status_code in (200, 201), resp.text
    return token


@pytest.fixture
async def outsider_token(client) -> str:
    return await _register_and_login(client, f"outsider-{uuid4().hex[:8]}@example.com")


# ---------------------------------------------------------------------------
# Group CRUD
# ---------------------------------------------------------------------------


class TestCreateGroup:
    async def test_create_success(self, client, owner_token, org):
        resp = await client.post(
            "/api/v1/groups",
            json={
                "name": "Finance Team",
                "description": "Finance department users",
                "tenant_id": org["slug"],
                "type": "SYSTEM",
                "attributes": {"department": "Finance", "clearance_level": 3, "region": "APAC"},
                "metadata": {"tags": ["finance", "internal"]},
            },
            headers=_auth(owner_token),
        )
        assert resp.status_code == 201, resp.text
        group = resp.json()["group"]
        assert group["name"] == "Finance Team"
        assert group["tenant_id"] == org["slug"]
        assert group["type"] == "SYSTEM"
        assert group["status"] == "ACTIVE"
        assert group["member_count"] == 0
        assert group["attributes"]["department"] == "Finance"
        assert group["metadata"]["tags"] == ["finance", "internal"]

    async def test_create_defaults_to_session_tenant(self, client, owner_token, org, unique_slug):
        # owner_token was minted *before* the org existed (see _create_org),
        # so claims.tenant_id isn't set on it yet — re-login to pick up the
        # now-single-org auto-selected tenant context, same pattern noted in
        # test_rbac_tenancy.py.
        fresh_token = await _register_and_login(client, f"owner-{unique_slug}@example.com")
        resp = await client.post(
            "/api/v1/groups", json={"name": "Default Tenant Group"}, headers=_auth(fresh_token)
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["group"]["tenant_id"] == org["slug"]
        assert resp.json()["group"]["type"] == "CUSTOM"

    async def test_create_requires_owner(self, client, member_token, org):
        resp = await client.post(
            "/api/v1/groups",
            json={"name": "Not Allowed", "tenant_id": org["slug"]},
            headers=_auth(member_token),
        )
        assert resp.status_code == 403

    async def test_create_without_tenant_context_fails(self, client, outsider_token):
        resp = await client.post("/api/v1/groups", json={"name": "No Tenant"}, headers=_auth(outsider_token))
        assert resp.status_code == 400

    async def test_create_with_parent_group(self, client, owner_token, org):
        parent = await client.post(
            "/api/v1/groups", json={"name": "Parent", "tenant_id": org["slug"]}, headers=_auth(owner_token)
        )
        parent_id = parent.json()["group"]["id"]

        child = await client.post(
            "/api/v1/groups",
            json={"name": "Child", "tenant_id": org["slug"], "parent_group_id": parent_id},
            headers=_auth(owner_token),
        )
        assert child.status_code == 201, child.text
        assert child.json()["group"]["parent_group_id"] == parent_id

    async def test_create_with_unknown_parent_returns_404(self, client, owner_token, org):
        resp = await client.post(
            "/api/v1/groups",
            json={"name": "Orphan", "tenant_id": org["slug"], "parent_group_id": str(uuid4())},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 404


class TestListGetGroups:
    async def test_list_returns_pagination_envelope(self, client, owner_token, org):
        await client.post(
            "/api/v1/groups", json={"name": "Listed", "tenant_id": org["slug"]}, headers=_auth(owner_token)
        )
        resp = await client.get(
            "/api/v1/groups", params={"tenant_id": org["slug"]}, headers=_auth(owner_token)
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 1
        assert body["total"] >= 1
        assert isinstance(body["groups"], list)

    async def test_list_requires_membership(self, client, outsider_token, org):
        resp = await client.get(
            "/api/v1/groups", params={"tenant_id": org["slug"]}, headers=_auth(outsider_token)
        )
        assert resp.status_code == 403

    async def test_get_by_id(self, client, owner_token, org):
        created = await client.post(
            "/api/v1/groups", json={"name": "Gettable", "tenant_id": org["slug"]}, headers=_auth(owner_token)
        )
        group_id = created.json()["group"]["id"]
        resp = await client.get(f"/api/v1/groups/{group_id}", headers=_auth(owner_token))
        assert resp.status_code == 200
        assert resp.json()["group"]["id"] == group_id

    async def test_get_unknown_returns_404(self, client, owner_token):
        resp = await client.get(f"/api/v1/groups/{uuid4()}", headers=_auth(owner_token))
        assert resp.status_code == 404


class TestUpdateDeleteGroup:
    async def test_update_success(self, client, owner_token, org):
        created = await client.post(
            "/api/v1/groups", json={"name": "Old Name", "tenant_id": org["slug"]}, headers=_auth(owner_token)
        )
        group_id = created.json()["group"]["id"]

        resp = await client.patch(
            f"/api/v1/groups/{group_id}",
            json={"name": "New Name", "status": "INACTIVE"},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["group"]
        assert body["name"] == "New Name"
        assert body["status"] == "INACTIVE"

    async def test_update_requires_owner(self, client, owner_token, member_token, org):
        created = await client.post(
            "/api/v1/groups", json={"name": "Protected", "tenant_id": org["slug"]}, headers=_auth(owner_token)
        )
        group_id = created.json()["group"]["id"]

        resp = await client.patch(
            f"/api/v1/groups/{group_id}", json={"name": "Hijacked"}, headers=_auth(member_token)
        )
        assert resp.status_code == 403

    async def test_update_parent_rejects_cycle(self, client, owner_token, org):
        parent = await client.post(
            "/api/v1/groups", json={"name": "P", "tenant_id": org["slug"]}, headers=_auth(owner_token)
        )
        parent_id = parent.json()["group"]["id"]
        child = await client.post(
            "/api/v1/groups",
            json={"name": "C", "tenant_id": org["slug"], "parent_group_id": parent_id},
            headers=_auth(owner_token),
        )
        child_id = child.json()["group"]["id"]

        resp = await client.patch(
            f"/api/v1/groups/{parent_id}", json={"parent_group_id": child_id}, headers=_auth(owner_token)
        )
        assert resp.status_code == 400

    async def test_delete_success(self, client, owner_token, org):
        created = await client.post(
            "/api/v1/groups", json={"name": "Throwaway", "tenant_id": org["slug"]}, headers=_auth(owner_token)
        )
        group_id = created.json()["group"]["id"]

        resp = await client.delete(f"/api/v1/groups/{group_id}", headers=_auth(owner_token))
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "message": "Group deleted successfully"}

        missing = await client.get(f"/api/v1/groups/{group_id}", headers=_auth(owner_token))
        assert missing.status_code == 404


# ---------------------------------------------------------------------------
# Group Membership CRUD
# ---------------------------------------------------------------------------


class TestCreateGroupMembership:
    async def test_create_success(self, client, owner_token, member_token, org):
        group = await client.post(
            "/api/v1/groups", json={"name": "Finance", "tenant_id": org["slug"]}, headers=_auth(owner_token)
        )
        group_id = group.json()["group"]["id"]
        user_id = (await client.get("/api/v1/users/me", headers=_auth(member_token))).json()["id"]

        resp = await client.post(
            "/api/v1/group-memberships",
            json={
                "user_id": user_id,
                "group_id": group_id,
                "tenant_id": org["slug"],
                "membership_type": "DIRECT",
                "role": "MEMBER",
                "attributes": {"access_level": "standard", "temporary": False},
            },
            headers=_auth(owner_token),
        )
        assert resp.status_code == 201, resp.text
        membership = resp.json()["membership"]
        assert membership["user_id"] == user_id
        assert membership["group_id"] == group_id
        assert membership["tenant_id"] == org["slug"]
        assert membership["status"] == "ACTIVE"

        group_after = await client.get(f"/api/v1/groups/{group_id}", headers=_auth(owner_token))
        assert group_after.json()["group"]["member_count"] == 1

    async def test_create_duplicate_returns_409(self, client, owner_token, member_token, org):
        group = await client.post(
            "/api/v1/groups", json={"name": "Dup", "tenant_id": org["slug"]}, headers=_auth(owner_token)
        )
        group_id = group.json()["group"]["id"]
        user_id = (await client.get("/api/v1/users/me", headers=_auth(member_token))).json()["id"]
        payload = {"user_id": user_id, "group_id": group_id}

        first = await client.post("/api/v1/group-memberships", json=payload, headers=_auth(owner_token))
        assert first.status_code == 201
        second = await client.post("/api/v1/group-memberships", json=payload, headers=_auth(owner_token))
        assert second.status_code == 409

    async def test_create_requires_owner(self, client, owner_token, member_token, org):
        group = await client.post(
            "/api/v1/groups", json={"name": "Gated", "tenant_id": org["slug"]}, headers=_auth(owner_token)
        )
        group_id = group.json()["group"]["id"]
        user_id = (await client.get("/api/v1/users/me", headers=_auth(member_token))).json()["id"]

        resp = await client.post(
            "/api/v1/group-memberships",
            json={"user_id": user_id, "group_id": group_id},
            headers=_auth(member_token),
        )
        assert resp.status_code == 403

    async def test_create_unknown_group_returns_404(self, client, owner_token, member_token):
        user_id = (await client.get("/api/v1/users/me", headers=_auth(member_token))).json()["id"]
        resp = await client.post(
            "/api/v1/group-memberships",
            json={"user_id": user_id, "group_id": str(uuid4())},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 404


class TestListGetGroupMemberships:
    async def test_list_by_group_id(self, client, owner_token, member_token, org):
        group = await client.post(
            "/api/v1/groups", json={"name": "Listable", "tenant_id": org["slug"]}, headers=_auth(owner_token)
        )
        group_id = group.json()["group"]["id"]
        user_id = (await client.get("/api/v1/users/me", headers=_auth(member_token))).json()["id"]
        await client.post(
            "/api/v1/group-memberships",
            json={"user_id": user_id, "group_id": group_id},
            headers=_auth(owner_token),
        )

        resp = await client.get(
            "/api/v1/group-memberships", params={"group_id": group_id}, headers=_auth(owner_token)
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["memberships"][0]["group_id"] == group_id

    async def test_list_by_self_user_id(self, client, owner_token, member_token, org):
        group = await client.post(
            "/api/v1/groups", json={"name": "SelfList", "tenant_id": org["slug"]}, headers=_auth(owner_token)
        )
        group_id = group.json()["group"]["id"]
        user_id = (await client.get("/api/v1/users/me", headers=_auth(member_token))).json()["id"]
        await client.post(
            "/api/v1/group-memberships",
            json={"user_id": user_id, "group_id": group_id},
            headers=_auth(owner_token),
        )

        resp = await client.get(
            "/api/v1/group-memberships", params={"user_id": user_id}, headers=_auth(member_token)
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_list_other_users_id_forbidden(self, client, member_token, outsider_token):
        other_id = (await client.get("/api/v1/users/me", headers=_auth(member_token))).json()["id"]
        resp = await client.get(
            "/api/v1/group-memberships", params={"user_id": other_id}, headers=_auth(outsider_token)
        )
        assert resp.status_code == 403

    async def test_get_unknown_returns_404(self, client, owner_token):
        resp = await client.get(f"/api/v1/group-memberships/{uuid4()}", headers=_auth(owner_token))
        assert resp.status_code == 404


class TestUpdateDeleteGroupMembership:
    async def test_update_role_and_status(self, client, owner_token, member_token, org):
        group = await client.post(
            "/api/v1/groups", json={"name": "Updatable", "tenant_id": org["slug"]}, headers=_auth(owner_token)
        )
        group_id = group.json()["group"]["id"]
        user_id = (await client.get("/api/v1/users/me", headers=_auth(member_token))).json()["id"]
        created = await client.post(
            "/api/v1/group-memberships",
            json={"user_id": user_id, "group_id": group_id},
            headers=_auth(owner_token),
        )
        membership_id = created.json()["membership"]["id"]

        resp = await client.patch(
            f"/api/v1/group-memberships/{membership_id}",
            json={"role": "ADMIN", "status": "INACTIVE"},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["membership"]
        assert body["role"] == "ADMIN"
        assert body["status"] == "INACTIVE"

    async def test_delete_success(self, client, owner_token, member_token, org):
        group = await client.post(
            "/api/v1/groups", json={"name": "Removable", "tenant_id": org["slug"]}, headers=_auth(owner_token)
        )
        group_id = group.json()["group"]["id"]
        user_id = (await client.get("/api/v1/users/me", headers=_auth(member_token))).json()["id"]
        created = await client.post(
            "/api/v1/group-memberships",
            json={"user_id": user_id, "group_id": group_id},
            headers=_auth(owner_token),
        )
        membership_id = created.json()["membership"]["id"]

        resp = await client.delete(f"/api/v1/group-memberships/{membership_id}", headers=_auth(owner_token))
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "message": "Group membership deleted successfully"}

        missing = await client.get(f"/api/v1/group-memberships/{membership_id}", headers=_auth(owner_token))
        assert missing.status_code == 404

        group_after = await client.get(f"/api/v1/groups/{group_id}", headers=_auth(owner_token))
        assert group_after.json()["group"]["member_count"] == 0
