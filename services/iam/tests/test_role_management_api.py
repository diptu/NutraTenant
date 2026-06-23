"""Role Management API tests — the genuinely new surface added by
Role_API_Specification_Extended.md on top of the pre-existing global-role
catalog (POST/DELETE /roles/{role_id}/assignments, GET /roles/assignments/{user_id},
covered by tests/test_hardened_authorization.py, and left unchanged here):
create-with-initial-permissions, pagination/search/filters on list, PUT update,
the {message,role}/{role}/{total,page,page_size,roles} response envelopes,
bulk permission assign/remove by code, GET .../permissions, POST/GET .../users,
clone, and activate/deactivate.
"""

from __future__ import annotations

from uuid import uuid4

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


async def _set_superuser(db_session, email: str, value: bool) -> None:
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    user.is_superuser = value
    await db_session.commit()


@pytest.fixture
async def superuser_token(client, db_session) -> str:
    email = f"role-su-{uuid4().hex[:8]}@example.com"
    token = await _register_and_login(client, email)
    await _set_superuser(db_session, email, True)
    return token


@pytest.fixture
async def tenant(client, superuser_token) -> dict:
    """A fresh organization, owned by a fresh (non-superuser) account."""
    owner_email = f"role-owner-{uuid4().hex[:8]}@example.com"
    owner_token = await _register_and_login(client, owner_email)
    owner_id = (await client.get("/api/v1/users/me", headers=_auth(owner_token))).json()["id"]

    slug = f"org-{uuid4().hex[:8]}"
    resp = await client.post(
        "/api/v1/organizations",
        json={"name": "Test Org", "slug": slug},
        headers=_auth(superuser_token),
    )
    assert resp.status_code == 201, resp.text
    organization_id = resp.json()["id"]

    add = await client.post(
        f"/api/v1/organizations/{organization_id}/members",
        json={"user_id": owner_id, "role_code": "owner"},
        headers=_auth(superuser_token),
    )
    assert add.status_code == 201, add.text

    return {
        "organization_id": organization_id,
        "slug": slug,
        "owner_email": owner_email,
        "owner_token": owner_token,
        "owner_id": owner_id,
    }


@pytest.fixture
async def member_in_tenant(client, superuser_token, tenant) -> dict:
    email = f"role-member-{uuid4().hex[:8]}@example.com"
    token = await _register_and_login(client, email)
    user_id = (await client.get("/api/v1/users/me", headers=_auth(token))).json()["id"]
    resp = await client.post(
        f"/api/v1/organizations/{tenant['organization_id']}/members",
        json={"user_id": user_id, "role_code": "member"},
        headers=_auth(superuser_token),
    )
    assert resp.status_code == 201, resp.text
    return {"email": email, "token": token, "id": user_id}


@pytest.fixture
async def seeded_permission_codes(client, superuser_token) -> list[str]:
    resp = await client.post(
        "/api/v1/permissions/seed",
        json={"resources": [f"roleapi{uuid4().hex[:6]}"]},
        headers=_auth(superuser_token),
    )
    assert resp.status_code == 200
    return resp.json()["created_permissions"]


# ---------------------------------------------------------------------------
# Create / List / Get
# ---------------------------------------------------------------------------


class TestCreateListGet:
    async def test_create_with_initial_permissions_and_priority(
        self, client, tenant, seeded_permission_codes
    ):
        resp = await client.post(
            "/api/v1/roles",
            json={
                "name": "Project Manager",
                "slug": "project_manager",
                "description": "Can manage projects",
                "priority": 50,
                "permissions": seeded_permission_codes[:2],
                "tenant_id": tenant["slug"],
            },
            headers=_auth(tenant["owner_token"]),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["message"] == "Role created successfully"
        role = body["role"]
        assert role["slug"] == "project_manager"
        assert role["priority"] == 50
        assert role["permissions_count"] == 2
        assert role["users_count"] == 0
        assert role["tenant_id"] == tenant["slug"]
        assert role["created_by"] == tenant["owner_id"]
        assert role["is_active"] is True
        assert role["is_system"] is False

    async def test_list_is_paginated_and_filterable(self, client, tenant):
        for slug in ("alpha_role", "beta_role"):
            resp = await client.post(
                "/api/v1/roles",
                json={"name": slug, "slug": slug, "tenant_id": tenant["slug"]},
                headers=_auth(tenant["owner_token"]),
            )
            assert resp.status_code == 201

        resp = await client.get(
            "/api/v1/roles",
            params={"page": 1, "page_size": 1, "search": "alpha", "tenant_id": tenant["slug"]},
            headers=_auth(tenant["owner_token"]),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 1
        assert body["page_size"] == 1
        assert body["total"] == 1
        assert body["roles"][0]["slug"] == "alpha_role"

    async def test_get_by_id(self, client, tenant):
        created = await client.post(
            "/api/v1/roles",
            json={"name": "Getme", "slug": "getme", "tenant_id": tenant["slug"]},
            headers=_auth(tenant["owner_token"]),
        )
        role_id = created.json()["role"]["id"]
        resp = await client.get(f"/api/v1/roles/{role_id}", headers=_auth(tenant["owner_token"]))
        assert resp.status_code == 200
        assert resp.json()["role"]["id"] == role_id

    async def test_get_unknown_returns_404(self, client, tenant):
        resp = await client.get(f"/api/v1/roles/{uuid4()}", headers=_auth(tenant["owner_token"]))
        assert resp.status_code == 404

    async def test_superuser_tenant_id_override_targets_other_tenant(self, client, superuser_token, tenant):
        """The escape hatch: a superuser with no session tenant context can
        still target an arbitrary tenant explicitly by slug."""
        resp = await client.post(
            "/api/v1/roles",
            json={"name": "Ops", "slug": "ops_role", "tenant_id": tenant["slug"]},
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["role"]["tenant_id"] == tenant["slug"]


# ---------------------------------------------------------------------------
# Update / Delete
# ---------------------------------------------------------------------------


class TestUpdateDelete:
    async def test_update_via_put(self, client, tenant):
        created = await client.post(
            "/api/v1/roles",
            json={"name": "Updatable", "slug": "updatable", "tenant_id": tenant["slug"]},
            headers=_auth(tenant["owner_token"]),
        )
        role_id = created.json()["role"]["id"]

        resp = await client.put(
            f"/api/v1/roles/{role_id}",
            json={"description": "Updated description", "priority": 75, "is_active": False},
            headers=_auth(tenant["owner_token"]),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["message"] == "Role updated successfully"
        assert body["role"]["description"] == "Updated description"
        assert body["role"]["priority"] == 75
        assert body["role"]["is_active"] is False
        assert body["role"]["updated_by"] == tenant["owner_id"]

    async def test_delete(self, client, tenant):
        created = await client.post(
            "/api/v1/roles",
            json={"name": "Deletable", "slug": "deletable", "tenant_id": tenant["slug"]},
            headers=_auth(tenant["owner_token"]),
        )
        role_id = created.json()["role"]["id"]

        resp = await client.delete(f"/api/v1/roles/{role_id}", headers=_auth(tenant["owner_token"]))
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "message": "Role deleted successfully"}

        missing = await client.get(f"/api/v1/roles/{role_id}", headers=_auth(tenant["owner_token"]))
        assert missing.status_code == 404


# ---------------------------------------------------------------------------
# Permissions (bulk by code)
# ---------------------------------------------------------------------------


class TestRolePermissionsBulk:
    async def test_assign_get_remove(self, client, tenant, seeded_permission_codes):
        created = await client.post(
            "/api/v1/roles",
            json={"name": "Perms", "slug": "perms_role", "tenant_id": tenant["slug"]},
            headers=_auth(tenant["owner_token"]),
        )
        role_id = created.json()["role"]["id"]

        assign = await client.post(
            f"/api/v1/roles/{role_id}/permissions",
            json={"permissions": seeded_permission_codes},
            headers=_auth(tenant["owner_token"]),
        )
        assert assign.status_code == 200
        assert assign.json()["permissions_count"] == len(seeded_permission_codes)

        listed = await client.get(
            f"/api/v1/roles/{role_id}/permissions", headers=_auth(tenant["owner_token"])
        )
        assert listed.status_code == 200
        assert listed.json()["role_id"] == role_id
        listed_names = {p["name"] for p in listed.json()["permissions"]}
        assert listed_names == set(seeded_permission_codes)

        removed = await client.request(
            "DELETE",
            f"/api/v1/roles/{role_id}/permissions",
            json={"permissions": seeded_permission_codes[:1]},
            headers=_auth(tenant["owner_token"]),
        )
        assert removed.status_code == 200
        assert removed.json() == {"success": True, "message": "Permissions removed successfully"}

        after = await client.get(f"/api/v1/roles/{role_id}/permissions", headers=_auth(tenant["owner_token"]))
        remaining_names = {p["name"] for p in after.json()["permissions"]}
        assert seeded_permission_codes[0] not in remaining_names
        assert seeded_permission_codes[1] in remaining_names


# ---------------------------------------------------------------------------
# Users (bulk assign)
# ---------------------------------------------------------------------------


class TestRoleUsers:
    async def test_assign_users_and_list(self, client, tenant, member_in_tenant):
        created = await client.post(
            "/api/v1/roles",
            json={"name": "Reviewer", "slug": "reviewer_role", "tenant_id": tenant["slug"]},
            headers=_auth(tenant["owner_token"]),
        )
        role_id = created.json()["role"]["id"]

        assign = await client.post(
            f"/api/v1/roles/{role_id}/users",
            json={"user_ids": [member_in_tenant["id"]]},
            headers=_auth(tenant["owner_token"]),
        )
        assert assign.status_code == 200
        assert assign.json() == {"success": True, "assigned_users": 1}

        users = await client.get(f"/api/v1/roles/{role_id}/users", headers=_auth(tenant["owner_token"]))
        assert users.status_code == 200
        body = users.json()
        assert body["role_id"] == role_id
        assert body["total"] == 1
        assert body["users"][0]["id"] == member_in_tenant["id"]
        assert body["users"][0]["email"] == member_in_tenant["email"]

        role_after = await client.get(f"/api/v1/roles/{role_id}", headers=_auth(tenant["owner_token"]))
        assert role_after.json()["role"]["users_count"] == 1

    async def test_assign_users_skips_non_members(self, client, tenant):
        created = await client.post(
            "/api/v1/roles",
            json={"name": "Reviewer2", "slug": "reviewer_role_2", "tenant_id": tenant["slug"]},
            headers=_auth(tenant["owner_token"]),
        )
        role_id = created.json()["role"]["id"]

        resp = await client.post(
            f"/api/v1/roles/{role_id}/users",
            json={"user_ids": [str(uuid4())]},
            headers=_auth(tenant["owner_token"]),
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "assigned_users": 0}

    async def test_assign_users_rejected_for_global_role(self, client, superuser_token):
        seeded = await client.post("/api/v1/roles/seed", headers=_auth(superuser_token))
        guest_role_id = next(r["id"] for r in seeded.json() if r["code"] == "guest")

        resp = await client.post(
            f"/api/v1/roles/{guest_role_id}/users",
            json={"user_ids": [str(uuid4())]},
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Clone / Activate / Deactivate
# ---------------------------------------------------------------------------


class TestCloneActivateDeactivate:
    async def test_clone_copies_permissions_and_priority(self, client, tenant, seeded_permission_codes):
        source = await client.post(
            "/api/v1/roles",
            json={
                "name": "Source",
                "slug": "source_role",
                "priority": 33,
                "permissions": seeded_permission_codes,
                "tenant_id": tenant["slug"],
            },
            headers=_auth(tenant["owner_token"]),
        )
        source_id = source.json()["role"]["id"]

        clone = await client.post(
            f"/api/v1/roles/{source_id}/clone",
            json={"name": "Source V2", "slug": "source_role_v2"},
            headers=_auth(tenant["owner_token"]),
        )
        assert clone.status_code == 201, clone.text
        body = clone.json()
        assert body["message"] == "Role cloned successfully"
        cloned = body["role"]
        assert cloned["id"] != source_id
        assert cloned["slug"] == "source_role_v2"
        assert cloned["priority"] == 33
        assert cloned["permissions_count"] == len(seeded_permission_codes)
        assert cloned["tenant_id"] == tenant["slug"]

        # The source role is untouched.
        source_after = await client.get(f"/api/v1/roles/{source_id}", headers=_auth(tenant["owner_token"]))
        assert source_after.json()["role"]["permissions_count"] == len(seeded_permission_codes)

    async def test_activate_deactivate(self, client, tenant):
        created = await client.post(
            "/api/v1/roles",
            json={"name": "Togglable", "slug": "togglable_role", "tenant_id": tenant["slug"]},
            headers=_auth(tenant["owner_token"]),
        )
        role_id = created.json()["role"]["id"]

        deactivate = await client.patch(
            f"/api/v1/roles/{role_id}/deactivate", headers=_auth(tenant["owner_token"])
        )
        assert deactivate.status_code == 200
        assert deactivate.json() == {"success": True, "status": "INACTIVE"}

        activate = await client.patch(
            f"/api/v1/roles/{role_id}/activate", headers=_auth(tenant["owner_token"])
        )
        assert activate.status_code == 200
        assert activate.json() == {"success": True, "status": "ACTIVE"}

        fetched = await client.get(f"/api/v1/roles/{role_id}", headers=_auth(tenant["owner_token"]))
        assert fetched.json()["role"]["is_active"] is True
