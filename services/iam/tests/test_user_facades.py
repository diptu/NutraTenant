"""Tests for the thin new facades introduced by the User Domain API
Specification and the User and Access APIs Specification:
/user-attributes, /user-groups, /user-profiles, /user-status, /access.

Each of these sits in front of already-tested underlying services
(UserService, GroupService, RoleService) under a new, simpler URL shape —
these tests check the new wire contract, not the underlying business logic
(already covered by test_user_org_resource_management.py / test_groups.py).
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
    return f"fac-{uuid4().hex[:8]}"


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


class TestUserAttributesFacade:
    async def test_get_and_put(self, client, owner_token, db_session):
        user_id = (await client.get("/api/v1/users/me", headers=_auth(owner_token))).json()["id"]
        await _set_superuser(db_session, user_id, True)

        resp = await client.put(
            f"/api/v1/user-attributes/{user_id}",
            json={"department": "Engineering", "designation": "Lead"},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": True}

        got = await client.get(f"/api/v1/user-attributes/{user_id}", headers=_auth(owner_token))
        assert got.status_code == 200
        assert got.json()["attributes"]["department"] == "Engineering"
        assert got.json()["attributes"]["designation"] == "Lead"
        await _set_superuser(db_session, user_id, False)

    async def test_put_requires_superuser(self, client, member_token, owner_token):
        user_id = (await client.get("/api/v1/users/me", headers=_auth(member_token))).json()["id"]
        resp = await client.put(
            f"/api/v1/user-attributes/{user_id}",
            json={"department": "Sales"},
            headers=_auth(member_token),
        )
        assert resp.status_code == 403


class TestUserProfilesFacade:
    async def test_get_defaults_empty(self, client, owner_token):
        resp = await client.get("/api/v1/user-profiles/me", headers=_auth(owner_token))
        assert resp.status_code == 200
        assert resp.json()["profile"] == {"avatar_url": "", "timezone": "", "locale": ""}

    async def test_put_partial_update(self, client, owner_token):
        resp = await client.put(
            "/api/v1/user-profiles/me",
            json={"avatar_url": "https://cdn.example.com/avatar.jpg", "timezone": "Asia/Dhaka"},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": True}

        got = await client.get("/api/v1/user-profiles/me", headers=_auth(owner_token))
        profile = got.json()["profile"]
        assert profile["avatar_url"] == "https://cdn.example.com/avatar.jpg"
        assert profile["timezone"] == "Asia/Dhaka"
        assert profile["locale"] == ""

        # A later partial update that omits avatar_url/timezone leaves them untouched.
        await client.put("/api/v1/user-profiles/me", json={"locale": "en-US"}, headers=_auth(owner_token))
        got2 = await client.get("/api/v1/user-profiles/me", headers=_auth(owner_token))
        profile2 = got2.json()["profile"]
        assert profile2["avatar_url"] == "https://cdn.example.com/avatar.jpg"
        assert profile2["locale"] == "en-US"


class TestUserStatusFacade:
    async def test_get_default_active(self, client, owner_token):
        user_id = (await client.get("/api/v1/users/me", headers=_auth(owner_token))).json()["id"]
        resp = await client.get(f"/api/v1/user-status/{user_id}", headers=_auth(owner_token))
        assert resp.status_code == 200
        assert resp.json() == {"status": "ACTIVE"}

    async def test_patch_requires_superuser(self, client, member_token, owner_token):
        user_id = (await client.get("/api/v1/users/me", headers=_auth(member_token))).json()["id"]
        resp = await client.patch(
            f"/api/v1/user-status/{user_id}", json={"status": "SUSPENDED"}, headers=_auth(member_token)
        )
        assert resp.status_code == 403

    async def test_patch_success(self, client, owner_token, member_token, db_session):
        # Acts on a *different* user (member) than the actor (owner) —
        # suspending the actor's own account would invalidate the very
        # token used for the follow-up GET (is_active becomes False).
        actor_id = (await client.get("/api/v1/users/me", headers=_auth(owner_token))).json()["id"]
        await _set_superuser(db_session, actor_id, True)
        target_id = (await client.get("/api/v1/users/me", headers=_auth(member_token))).json()["id"]

        resp = await client.patch(
            f"/api/v1/user-status/{target_id}",
            json={"status": "SUSPENDED"},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 200
        assert resp.json() == {"user_id": target_id, "status": "SUSPENDED"}

        got = await client.get(f"/api/v1/user-status/{target_id}", headers=_auth(owner_token))
        assert got.json() == {"status": "SUSPENDED"}
        await _set_superuser(db_session, actor_id, False)

    async def test_get_other_user_forbidden(self, client, member_token, owner_token):
        owner_id = (await client.get("/api/v1/users/me", headers=_auth(owner_token))).json()["id"]
        resp = await client.get(f"/api/v1/user-status/{owner_id}", headers=_auth(member_token))
        assert resp.status_code == 403


class TestAccessSummary:
    async def test_get_own_access_summary(self, client, owner_token, org):
        owner_id = (await client.get("/api/v1/users/me", headers=_auth(owner_token))).json()["id"]
        resp = await client.get(f"/api/v1/access/{owner_id}", headers=_auth(owner_token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == owner_id
        assert "owner" in body["roles"]
        assert isinstance(body["permissions"], list)
        assert isinstance(body["effective_attributes"], dict)

    async def test_get_other_user_forbidden(self, client, member_token, owner_token):
        owner_id = (await client.get("/api/v1/users/me", headers=_auth(owner_token))).json()["id"]
        resp = await client.get(f"/api/v1/access/{owner_id}", headers=_auth(member_token))
        assert resp.status_code == 403


class TestUserGroupsFacade:
    async def test_create_list_and_bulk_add_members(self, client, owner_token, member_token, unique_slug):
        # owner_token was minted before the org existed (see the org
        # fixture), so claims.tenant_id isn't set on it yet — /user-groups
        # always resolves the tenant from the session (no explicit
        # tenant_id override, unlike /groups), so re-login first.
        owner_token = await _register_and_login(client, f"owner-{unique_slug}@example.com")

        created = await client.post(
            "/api/v1/user-groups",
            json={"name": "Finance Team", "description": "Finance department users"},
            headers=_auth(owner_token),
        )
        assert created.status_code == 201, created.text
        group_id = created.json()["group_id"]

        listed = await client.get("/api/v1/user-groups", headers=_auth(owner_token))
        assert listed.status_code == 200
        assert any(g["group_id"] == group_id for g in listed.json()["groups"])

        member_id = (await client.get("/api/v1/users/me", headers=_auth(member_token))).json()["id"]
        added = await client.post(
            f"/api/v1/user-groups/{group_id}/members",
            json={"user_ids": [member_id]},
            headers=_auth(owner_token),
        )
        assert added.status_code == 200, added.text
        assert added.json() == {"added_count": 1}

        # Re-adding the same user is a no-op (already a member), not an error.
        added_again = await client.post(
            f"/api/v1/user-groups/{group_id}/members",
            json={"user_ids": [member_id]},
            headers=_auth(owner_token),
        )
        assert added_again.json() == {"added_count": 0}

        removed = await client.delete(
            f"/api/v1/user-groups/{group_id}/members/{member_id}", headers=_auth(owner_token)
        )
        assert removed.status_code == 204

    async def test_create_requires_owner(self, client, member_token, unique_slug):
        # member_token was minted before joining the org (see the
        # member_token fixture), so claims.tenant_id isn't set on it yet —
        # re-login to pick up the now-tenant-bound session, same pattern as
        # tests/test_groups.py's test_create_defaults_to_session_tenant.
        fresh_token = await _register_and_login(client, f"member-{unique_slug}@example.com")
        resp = await client.post(
            "/api/v1/user-groups", json={"name": "Not Allowed"}, headers=_auth(fresh_token)
        )
        assert resp.status_code == 403
