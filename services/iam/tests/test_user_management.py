"""Tests for user management endpoints (CRUD, profile, activate/deactivate, search).

Updated to the current DDD architecture (app.infrastructure.* / app.services.*)
and the actual current contract:
  - GET /users returns a plain list, not a `{items, total, page, page_size}`
    envelope (changing that would break the already-tested current behavior
    in tests/test_user_org_resource_management.py).
  - There's no separate `/users/{id}/profile` sub-resource — `full_name`
    lives directly on the user, edited via `PATCH /users/{id}`.
  - Activation/verification toggles are admin-only and go through the
    dedicated `/activate` / `/deactivate` endpoints, not a generic PATCH
    with an `is_active` field (and there's no `is_verified` toggle at all
    yet — that assertion is dropped rather than inventing a new endpoint
    here).
"""

from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from app.modules.users.models import User
from sqlalchemy import select

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _register(client, email: str, password: str = "Password123!") -> dict:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _login_token(client, email: str, password: str = "Password123!") -> str:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _make_superuser(db_session, user_id: UUID | str) -> None:
    result = await db_session.execute(select(User).where(User.id == UUID(str(user_id))))
    user = result.scalar_one()
    user.is_superuser = True
    db_session.add(user)
    await db_session.commit()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def regular_user(client):
    return await _register(client, "regular@test.com")


@pytest.fixture
async def regular_token(client, regular_user):
    return await _login_token(client, "regular@test.com")


@pytest.fixture
async def admin_user(client, db_session):
    data = await _register(client, "admin@test.com")
    await _make_superuser(db_session, data["id"])
    return data


@pytest.fixture
async def admin_token(client, admin_user):
    return await _login_token(client, "admin@test.com")


# ---------------------------------------------------------------------------
# GET /users/me
# ---------------------------------------------------------------------------


class TestGetMe:
    @pytest.mark.anyio
    async def test_returns_own_profile(self, client, regular_token) -> None:
        resp = await client.get("/api/v1/users/me", headers=_auth(regular_token))
        assert resp.status_code == 200
        assert resp.json()["email"] == "regular@test.com"

    @pytest.mark.anyio
    async def test_unauthenticated_returns_401(self, client) -> None:
        resp = await client.get("/api/v1/users/me")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /users  (admin only)
# ---------------------------------------------------------------------------


class TestListUsers:
    @pytest.mark.anyio
    async def test_admin_can_list_users(self, client, admin_token, regular_user) -> None:
        resp = await client.get("/api/v1/users", headers=_auth(admin_token))
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

    @pytest.mark.anyio
    async def test_non_admin_gets_403(self, client, regular_token) -> None:
        resp = await client.get("/api/v1/users", headers=_auth(regular_token))
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_search_by_email(self, client, admin_token, regular_user) -> None:
        resp = await client.get("/api/v1/users", params={"q": "regular"}, headers=_auth(admin_token))
        assert resp.status_code == 200
        items = resp.json()
        assert items
        assert all("regular" in u["email"] for u in items)


# ---------------------------------------------------------------------------
# GET /users/{id}
# ---------------------------------------------------------------------------


class TestGetUser:
    @pytest.mark.anyio
    async def test_admin_can_get_any_user(self, client, admin_token, regular_user) -> None:
        resp = await client.get(f"/api/v1/users/{regular_user['id']}", headers=_auth(admin_token))
        assert resp.status_code == 200
        assert resp.json()["id"] == regular_user["id"]

    @pytest.mark.anyio
    async def test_user_can_get_own_record(self, client, regular_token, regular_user) -> None:
        resp = await client.get(f"/api/v1/users/{regular_user['id']}", headers=_auth(regular_token))
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_user_cannot_get_other_user(self, client, regular_token, admin_user) -> None:
        resp = await client.get(f"/api/v1/users/{admin_user['id']}", headers=_auth(regular_token))
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_returns_404_for_unknown_user(self, client, admin_token) -> None:
        resp = await client.get(f"/api/v1/users/{uuid.uuid4()}", headers=_auth(admin_token))
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /users/{id}  (full_name — self or admin)
# ---------------------------------------------------------------------------


class TestUpdateUser:
    @pytest.mark.anyio
    async def test_admin_can_update_any_users_full_name(self, client, admin_token, regular_user) -> None:
        resp = await client.patch(
            f"/api/v1/users/{regular_user['id']}",
            json={"full_name": "Admin Set Name"},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["full_name"] == "Admin Set Name"

    @pytest.mark.anyio
    async def test_user_can_update_own_full_name(self, client, regular_token, regular_user) -> None:
        resp = await client.patch(
            f"/api/v1/users/{regular_user['id']}",
            json={"full_name": "Self Set Name"},
            headers=_auth(regular_token),
        )
        assert resp.status_code == 200
        assert resp.json()["full_name"] == "Self Set Name"

    @pytest.mark.anyio
    async def test_user_cannot_update_other_users_name(self, client, regular_token, admin_user) -> None:
        resp = await client.patch(
            f"/api/v1/users/{admin_user['id']}",
            json={"full_name": "Hacker"},
            headers=_auth(regular_token),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /users/{id}/activate  and  /deactivate  (admin only)
# ---------------------------------------------------------------------------


class TestActivateDeactivate:
    @pytest.mark.anyio
    async def test_deactivate_then_activate(self, client, admin_token, regular_user) -> None:
        resp = await client.post(f"/api/v1/users/{regular_user['id']}/deactivate", headers=_auth(admin_token))
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

        resp = await client.post(f"/api/v1/users/{regular_user['id']}/activate", headers=_auth(admin_token))
        assert resp.status_code == 200
        assert resp.json()["is_active"] is True

    @pytest.mark.anyio
    async def test_non_admin_cannot_deactivate(self, client, regular_token, regular_user) -> None:
        resp = await client.post(
            f"/api/v1/users/{regular_user['id']}/deactivate",
            headers=_auth(regular_token),
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_deactivated_user_loses_access(
        self, client, admin_token, regular_token, regular_user
    ) -> None:
        """A deactivated user's existing access token stops working immediately
        — get_current_user checks live `is_active` on every request."""
        await client.post(f"/api/v1/users/{regular_user['id']}/deactivate", headers=_auth(admin_token))
        resp = await client.get("/api/v1/users/me", headers=_auth(regular_token))
        assert resp.status_code == 401
