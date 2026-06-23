"""POST/DELETE /api/v1/users/{user_id}/permissions — direct, org-scoped
permission grants independent of the user's role (see
app.infrastructure.db.models.associations.UserPermissionGrant and
app.modules.users.service.UserService.add_permissions/remove_permissions).

Additive only: these are stored and merged into the Common User Object's
`permissions` list, but not (yet) read by the RBAC fast-path or
PolicyEngineService.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from app.modules.permissions.models import Permission
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
    result = await db_session.execute(select(User).where(User.id == uuid.UUID(str(user_id))))
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


async def _create_org(client, token: str, *, slug: str, name: str = "Acme Inc") -> dict:
    resp = await client.post("/api/v1/organizations", json={"name": name, "slug": slug}, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _seed_permission(db_session, code: str) -> Permission:
    resource, action = code.split(":", 1)
    permission = Permission(
        id=uuid.uuid4(),
        name=code,
        code=code,
        resource=resource,
        action=action,
        description=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(permission)
    await db_session.commit()
    return permission


@pytest.fixture
async def permission_codes(db_session) -> list[str]:
    await _seed_permission(db_session, "document:create")
    await _seed_permission(db_session, "document:update")
    await _seed_permission(db_session, "document:delete")
    return ["document:create", "document:update", "document:delete"]


class TestAddUserPermissions:
    async def test_grants_are_merged_into_common_user_object(self, client, db_session, permission_codes):
        super_token = await _superuser_token(client, db_session, "root-perm@test.com")
        org = await _create_org(client, super_token, slug="perm-org-a")
        bob_token = await _login_token(client, (await _register(client, "bob-perm@test.com"))["email"])
        bob_id = (await client.get("/api/v1/users/me", headers=_auth(bob_token))).json()["id"]
        await client.post(
            f"/api/v1/organizations/{org['id']}/members",
            json={"user_id": bob_id, "role_code": "member"},
            headers=_auth(super_token),
        )

        resp = await client.post(
            f"/api/v1/users/{bob_id}/permissions",
            json={"permissions": ["document:create", "document:update"]},
            headers=_auth(super_token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "success": True,
            "permissions": ["document:create", "document:update"],
        }

        profile = await client.get(f"/api/v1/users/{bob_id}", headers=_auth(super_token))
        assert profile.status_code == 200
        assert set(profile.json()["permissions"]) == {"document:create", "document:update"}

    async def test_adding_is_idempotent(self, client, db_session, permission_codes):
        super_token = await _superuser_token(client, db_session, "root-perm2@test.com")
        org = await _create_org(client, super_token, slug="perm-org-b")
        bob_token = await _login_token(client, (await _register(client, "bob-perm2@test.com"))["email"])
        bob_id = (await client.get("/api/v1/users/me", headers=_auth(bob_token))).json()["id"]
        await client.post(
            f"/api/v1/organizations/{org['id']}/members",
            json={"user_id": bob_id, "role_code": "member"},
            headers=_auth(super_token),
        )

        for _ in range(2):
            resp = await client.post(
                f"/api/v1/users/{bob_id}/permissions",
                json={"permissions": ["document:create"]},
                headers=_auth(super_token),
            )
            assert resp.status_code == 200
            assert resp.json()["permissions"] == ["document:create"]

    async def test_unknown_permission_code_returns_404(self, client, db_session):
        super_token = await _superuser_token(client, db_session, "root-perm3@test.com")
        org = await _create_org(client, super_token, slug="perm-org-c")
        bob_token = await _login_token(client, (await _register(client, "bob-perm3@test.com"))["email"])
        bob_id = (await client.get("/api/v1/users/me", headers=_auth(bob_token))).json()["id"]
        await client.post(
            f"/api/v1/organizations/{org['id']}/members",
            json={"user_id": bob_id, "role_code": "member"},
            headers=_auth(super_token),
        )

        resp = await client.post(
            f"/api/v1/users/{bob_id}/permissions",
            json={"permissions": ["no-such-permission"]},
            headers=_auth(super_token),
        )
        assert resp.status_code == 404

    async def test_ambiguous_tenant_without_query_param_returns_400(
        self, client, db_session, permission_codes
    ):
        super_token = await _superuser_token(client, db_session, "root-perm4@test.com")
        bob_token = await _login_token(client, (await _register(client, "bob-perm4@test.com"))["email"])
        bob_id = (await client.get("/api/v1/users/me", headers=_auth(bob_token))).json()["id"]
        # bob belongs to zero organizations.

        resp = await client.post(
            f"/api/v1/users/{bob_id}/permissions",
            json={"permissions": ["document:create"]},
            headers=_auth(super_token),
        )
        assert resp.status_code == 400

    async def test_tenant_id_query_param_disambiguates_multiple_orgs(
        self, client, db_session, permission_codes
    ):
        super_token = await _superuser_token(client, db_session, "root-perm5@test.com")
        org_a = await _create_org(client, super_token, slug="perm-org-d")
        org_b = await _create_org(client, super_token, slug="perm-org-e")
        bob_token = await _login_token(client, (await _register(client, "bob-perm5@test.com"))["email"])
        bob_id = (await client.get("/api/v1/users/me", headers=_auth(bob_token))).json()["id"]
        for org in (org_a, org_b):
            resp = await client.post(
                f"/api/v1/organizations/{org['id']}/members",
                json={"user_id": bob_id, "role_code": "member"},
                headers=_auth(super_token),
            )
            assert resp.status_code == 201

        resp = await client.post(
            f"/api/v1/users/{bob_id}/permissions",
            params={"tenant_id": "perm-org-e"},
            json={"permissions": ["document:create"]},
            headers=_auth(super_token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["permissions"] == ["document:create"]

        # Scoped to org_e only — org_d's grant context is untouched.
        profile_d = await client.get(
            f"/api/v1/users/{bob_id}", params={"tenant_id": "perm-org-d"}, headers=_auth(super_token)
        )
        assert profile_d.json()["permissions"] == []
        profile_e = await client.get(
            f"/api/v1/users/{bob_id}", params={"tenant_id": "perm-org-e"}, headers=_auth(super_token)
        )
        assert profile_e.json()["permissions"] == ["document:create"]

    async def test_requires_superuser(self, client, db_session, permission_codes):
        alice_token = await _login_token(client, (await _register(client, "alice-perm@test.com"))["email"])
        alice_id = (await client.get("/api/v1/users/me", headers=_auth(alice_token))).json()["id"]

        resp = await client.post(
            f"/api/v1/users/{alice_id}/permissions",
            json={"permissions": ["document:create"]},
            headers=_auth(alice_token),
        )
        assert resp.status_code == 403


class TestRemoveUserPermissions:
    async def test_removes_a_granted_permission(self, client, db_session, permission_codes):
        super_token = await _superuser_token(client, db_session, "root-perm6@test.com")
        org = await _create_org(client, super_token, slug="perm-org-f")
        bob_token = await _login_token(client, (await _register(client, "bob-perm6@test.com"))["email"])
        bob_id = (await client.get("/api/v1/users/me", headers=_auth(bob_token))).json()["id"]
        await client.post(
            f"/api/v1/organizations/{org['id']}/members",
            json={"user_id": bob_id, "role_code": "member"},
            headers=_auth(super_token),
        )
        await client.post(
            f"/api/v1/users/{bob_id}/permissions",
            json={"permissions": ["document:create", "document:update"]},
            headers=_auth(super_token),
        )

        resp = await client.request(
            "DELETE",
            f"/api/v1/users/{bob_id}/permissions",
            json={"permissions": ["document:update"]},
            headers=_auth(super_token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success": True}

        profile = await client.get(f"/api/v1/users/{bob_id}", headers=_auth(super_token))
        assert profile.json()["permissions"] == ["document:create"]

    async def test_removing_ungranted_permission_is_idempotent(self, client, db_session, permission_codes):
        super_token = await _superuser_token(client, db_session, "root-perm7@test.com")
        org = await _create_org(client, super_token, slug="perm-org-g")
        bob_token = await _login_token(client, (await _register(client, "bob-perm7@test.com"))["email"])
        bob_id = (await client.get("/api/v1/users/me", headers=_auth(bob_token))).json()["id"]
        await client.post(
            f"/api/v1/organizations/{org['id']}/members",
            json={"user_id": bob_id, "role_code": "member"},
            headers=_auth(super_token),
        )

        resp = await client.request(
            "DELETE",
            f"/api/v1/users/{bob_id}/permissions",
            json={"permissions": ["document:delete"]},
            headers=_auth(super_token),
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": True}

    async def test_unknown_permission_code_returns_404(self, client, db_session):
        super_token = await _superuser_token(client, db_session, "root-perm8@test.com")
        org = await _create_org(client, super_token, slug="perm-org-h")
        bob_token = await _login_token(client, (await _register(client, "bob-perm8@test.com"))["email"])
        bob_id = (await client.get("/api/v1/users/me", headers=_auth(bob_token))).json()["id"]
        await client.post(
            f"/api/v1/organizations/{org['id']}/members",
            json={"user_id": bob_id, "role_code": "member"},
            headers=_auth(super_token),
        )

        resp = await client.request(
            "DELETE",
            f"/api/v1/users/{bob_id}/permissions",
            json={"permissions": ["no-such-permission"]},
            headers=_auth(super_token),
        )
        assert resp.status_code == 404

    async def test_requires_superuser(self, client, db_session, permission_codes):
        alice_token = await _login_token(client, (await _register(client, "alice-perm2@test.com"))["email"])
        alice_id = (await client.get("/api/v1/users/me", headers=_auth(alice_token))).json()["id"]

        resp = await client.request(
            "DELETE",
            f"/api/v1/users/{alice_id}/permissions",
            json={"permissions": ["document:create"]},
            headers=_auth(alice_token),
        )
        assert resp.status_code == 403
