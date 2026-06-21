"""User CRUD/search/attributes, organization lifecycle/membership, and the resource
classification catalog (checklist sections 3 & 4).

Named distinctly from the broken legacy tests/test_user_management.py (old,
pre-migration module paths — uncollectible, out of scope here).
"""

from __future__ import annotations

import pytest
from app.api.v1.dependencies import get_token_cache
from app.infrastructure.db.models.user import User
from app.infrastructure.security.token_cache import InMemoryTokenCache
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client_ctx(app):
    cache = InMemoryTokenCache()
    app.dependency_overrides[get_token_cache] = lambda: cache
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as ac:
        yield ac


async def _register_and_login(client: AsyncClient, email: str, *, full_name: str | None = None) -> str:
    password = "Sup3rSecret!23"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _set_superuser(db_session, email: str, value: bool) -> None:
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    user.is_superuser = value
    await db_session.commit()


async def _make_superuser(db_session, email: str) -> None:
    await _set_superuser(db_session, email, True)


async def _create_org(
    client_ctx,
    db_session,
    token: str,
    *,
    email: str,
    slug: str,
    name: str = "Acme",
    description: str | None = None,
) -> dict:
    """Organization creation is superuser-only — transiently promotes the
    acting account, then demotes it back so the rest of the test still
    exercises regular non-superuser behavior."""
    await _make_superuser(db_session, email)
    payload: dict = {"name": name, "slug": slug}
    if description is not None:
        payload["description"] = description
    resp = await client_ctx.post("/api/v1/organizations", json=payload, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    await _set_superuser(db_session, email, False)
    return resp.json()


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


async def test_get_my_profile(client_ctx):
    token = await _register_and_login(client_ctx, "alice@example.com", full_name="Alice")
    response = await client_ctx.get("/api/v1/users/me", headers=_auth(token))
    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.com"
    assert response.json()["full_name"] == "Alice"


async def test_list_users_requires_superuser(client_ctx):
    token = await _register_and_login(client_ctx, "alice@example.com")
    response = await client_ctx.get("/api/v1/users", headers=_auth(token))
    assert response.status_code == 403


async def test_list_users_as_superuser_supports_search(client_ctx, db_session):
    admin_token = await _register_and_login(client_ctx, "admin@example.com")
    await _make_superuser(db_session, "admin@example.com")
    await _register_and_login(client_ctx, "bob@example.com", full_name="Bob Builder")

    response = await client_ctx.get("/api/v1/users", params={"q": "bob"}, headers=_auth(admin_token))
    assert response.status_code == 200
    emails = {u["email"] for u in response.json()}
    assert "bob@example.com" in emails
    assert "admin@example.com" not in emails


async def test_get_other_user_forbidden_for_non_superuser(client_ctx):
    alice_token = await _register_and_login(client_ctx, "alice@example.com")
    bob_token = await _register_and_login(client_ctx, "bob@example.com")
    bob_id = (await client_ctx.get("/api/v1/users/me", headers=_auth(bob_token))).json()["id"]

    response = await client_ctx.get(f"/api/v1/users/{bob_id}", headers=_auth(alice_token))
    assert response.status_code == 403


async def test_get_other_user_allowed_for_superuser(client_ctx, db_session):
    admin_token = await _register_and_login(client_ctx, "admin@example.com")
    await _make_superuser(db_session, "admin@example.com")
    bob_token = await _register_and_login(client_ctx, "bob@example.com")
    bob_id = (await client_ctx.get("/api/v1/users/me", headers=_auth(bob_token))).json()["id"]

    response = await client_ctx.get(f"/api/v1/users/{bob_id}", headers=_auth(admin_token))
    assert response.status_code == 200
    assert response.json()["email"] == "bob@example.com"


async def test_update_own_profile_succeeds_update_others_forbidden(client_ctx):
    alice_token = await _register_and_login(client_ctx, "alice@example.com")
    alice_id = (await client_ctx.get("/api/v1/users/me", headers=_auth(alice_token))).json()["id"]
    bob_token = await _register_and_login(client_ctx, "bob@example.com")

    own_update = await client_ctx.patch(
        f"/api/v1/users/{alice_id}",
        json={"full_name": "Alice Updated"},
        headers=_auth(alice_token),
    )
    assert own_update.status_code == 200
    assert own_update.json()["full_name"] == "Alice Updated"

    other_update = await client_ctx.patch(
        f"/api/v1/users/{alice_id}",
        json={"full_name": "Hijacked"},
        headers=_auth(bob_token),
    )
    assert other_update.status_code == 403


async def test_update_attributes_requires_superuser_and_merges(client_ctx, db_session):
    admin_token = await _register_and_login(client_ctx, "admin@example.com")
    await _make_superuser(db_session, "admin@example.com")
    bob_token = await _register_and_login(client_ctx, "bob@example.com")
    bob_id = (await client_ctx.get("/api/v1/users/me", headers=_auth(bob_token))).json()["id"]

    forbidden = await client_ctx.patch(
        f"/api/v1/users/{bob_id}/attributes",
        json={"attributes": {"department": "Sales"}},
        headers=_auth(bob_token),
    )
    assert forbidden.status_code == 403

    first = await client_ctx.patch(
        f"/api/v1/users/{bob_id}/attributes",
        json={"attributes": {"department": "Engineering"}},
        headers=_auth(admin_token),
    )
    assert first.status_code == 200
    assert first.json()["attributes"] == {"department": "Engineering"}

    second = await client_ctx.patch(
        f"/api/v1/users/{bob_id}/attributes",
        json={"attributes": {"clearance": "L3"}},
        headers=_auth(admin_token),
    )
    assert second.status_code == 200
    assert second.json()["attributes"] == {
        "department": "Engineering",
        "clearance": "L3",
    }


async def test_activate_deactivate_user(client_ctx, db_session):
    admin_token = await _register_and_login(client_ctx, "admin@example.com")
    await _make_superuser(db_session, "admin@example.com")
    bob_token = await _register_and_login(client_ctx, "bob@example.com")
    bob_id = (await client_ctx.get("/api/v1/users/me", headers=_auth(bob_token))).json()["id"]

    deactivated = await client_ctx.post(f"/api/v1/users/{bob_id}/deactivate", headers=_auth(admin_token))
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    # Bob's still-unexpired access token is now rejected — get_current_user
    # checks live `is_active` on every request, not just at login time.
    blocked = await client_ctx.get("/api/v1/users/me", headers=_auth(bob_token))
    assert blocked.status_code == 401

    reactivated = await client_ctx.post(f"/api/v1/users/{bob_id}/activate", headers=_auth(admin_token))
    assert reactivated.status_code == 200
    assert reactivated.json()["is_active"] is True


async def test_delete_user(client_ctx, db_session):
    admin_token = await _register_and_login(client_ctx, "admin@example.com")
    await _make_superuser(db_session, "admin@example.com")
    bob_token = await _register_and_login(client_ctx, "bob@example.com")
    bob_id = (await client_ctx.get("/api/v1/users/me", headers=_auth(bob_token))).json()["id"]

    response = await client_ctx.delete(f"/api/v1/users/{bob_id}", headers=_auth(admin_token))
    assert response.status_code == 204

    follow_up = await client_ctx.get(f"/api/v1/users/{bob_id}", headers=_auth(admin_token))
    assert follow_up.status_code == 404


# ---------------------------------------------------------------------------
# Organization lifecycle & membership
# ---------------------------------------------------------------------------


async def test_create_organization_provisions_owner_membership(client_ctx, db_session):
    token = await _register_and_login(client_ctx, "owner@example.com")
    org = await _create_org(
        client_ctx,
        db_session,
        token,
        email="owner@example.com",
        slug="acme",
        description="Acme Inc",
    )
    org_id = org["id"]

    members = await client_ctx.get(f"/api/v1/organizations/{org_id}/members", headers=_auth(token))
    assert members.status_code == 200
    assert len(members.json()) == 1
    assert members.json()[0]["role_code"] == "owner"


async def test_create_organization_duplicate_slug_rejected(client_ctx, db_session):
    token = await _register_and_login(client_ctx, "owner@example.com")
    await _create_org(client_ctx, db_session, token, email="owner@example.com", slug="acme")
    await _make_superuser(db_session, "owner@example.com")
    response = await client_ctx.post(
        "/api/v1/organizations",
        json={"name": "Acme", "slug": "acme"},
        headers=_auth(token),
    )
    assert response.status_code == 409


async def test_list_my_organizations_excludes_others(client_ctx, db_session):
    owner_token = await _register_and_login(client_ctx, "owner@example.com")
    stranger_token = await _register_and_login(client_ctx, "stranger@example.com")
    await _create_org(client_ctx, db_session, owner_token, email="owner@example.com", slug="acme")

    owner_list = await client_ctx.get("/api/v1/organizations", headers=_auth(owner_token))
    assert len(owner_list.json()) == 1

    stranger_list = await client_ctx.get("/api/v1/organizations", headers=_auth(stranger_token))
    assert len(stranger_list.json()) == 0


async def test_get_organization_requires_membership(client_ctx, db_session):
    owner_token = await _register_and_login(client_ctx, "owner@example.com")
    stranger_token = await _register_and_login(client_ctx, "stranger@example.com")
    org_id = (await _create_org(client_ctx, db_session, owner_token, email="owner@example.com", slug="acme"))[
        "id"
    ]

    forbidden = await client_ctx.get(f"/api/v1/organizations/{org_id}", headers=_auth(stranger_token))
    assert forbidden.status_code == 403

    allowed = await client_ctx.get(f"/api/v1/organizations/{org_id}", headers=_auth(owner_token))
    assert allowed.status_code == 200


async def test_update_organization_requires_owner(client_ctx, db_session):
    owner_token = await _register_and_login(client_ctx, "owner@example.com")
    member_token = await _register_and_login(client_ctx, "member@example.com")
    member_id = (await client_ctx.get("/api/v1/users/me", headers=_auth(member_token))).json()["id"]
    org_id = (await _create_org(client_ctx, db_session, owner_token, email="owner@example.com", slug="acme"))[
        "id"
    ]
    await client_ctx.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"user_id": member_id, "role_code": "member"},
        headers=_auth(owner_token),
    )

    forbidden = await client_ctx.patch(
        f"/api/v1/organizations/{org_id}",
        json={"name": "Hijacked"},
        headers=_auth(member_token),
    )
    assert forbidden.status_code == 403

    allowed = await client_ctx.patch(
        f"/api/v1/organizations/{org_id}",
        json={"name": "Acme Corp"},
        headers=_auth(owner_token),
    )
    assert allowed.status_code == 200
    assert allowed.json()["name"] == "Acme Corp"


async def test_add_member_merges_org_default_attributes(client_ctx, db_session):
    owner_token = await _register_and_login(client_ctx, "owner@example.com")
    member_token = await _register_and_login(client_ctx, "member@example.com")
    member_id = (await client_ctx.get("/api/v1/users/me", headers=_auth(member_token))).json()["id"]
    org_id = (await _create_org(client_ctx, db_session, owner_token, email="owner@example.com", slug="acme"))[
        "id"
    ]

    await client_ctx.patch(
        f"/api/v1/organizations/{org_id}",
        json={"default_attributes": {"region": "EU", "department": "Unassigned"}},
        headers=_auth(owner_token),
    )

    add_response = await client_ctx.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"user_id": member_id, "role_code": "member"},
        headers=_auth(owner_token),
    )
    assert add_response.status_code == 201

    profile = await client_ctx.get("/api/v1/users/me", headers=_auth(member_token))
    assert profile.json()["attributes"] == {"region": "EU", "department": "Unassigned"}


async def test_add_member_duplicate_rejected(client_ctx, db_session):
    owner_token = await _register_and_login(client_ctx, "owner@example.com")
    member_token = await _register_and_login(client_ctx, "member@example.com")
    member_id = (await client_ctx.get("/api/v1/users/me", headers=_auth(member_token))).json()["id"]
    org_id = (await _create_org(client_ctx, db_session, owner_token, email="owner@example.com", slug="acme"))[
        "id"
    ]
    body = {"user_id": member_id, "role_code": "member"}
    await client_ctx.post(f"/api/v1/organizations/{org_id}/members", json=body, headers=_auth(owner_token))
    response = await client_ctx.post(
        f"/api/v1/organizations/{org_id}/members", json=body, headers=_auth(owner_token)
    )
    assert response.status_code == 409


async def test_add_member_unknown_role_rejected(client_ctx, db_session):
    owner_token = await _register_and_login(client_ctx, "owner@example.com")
    member_token = await _register_and_login(client_ctx, "member@example.com")
    member_id = (await client_ctx.get("/api/v1/users/me", headers=_auth(member_token))).json()["id"]
    org_id = (await _create_org(client_ctx, db_session, owner_token, email="owner@example.com", slug="acme"))[
        "id"
    ]

    response = await client_ctx.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"user_id": member_id, "role_code": "superadmin"},
        headers=_auth(owner_token),
    )
    assert response.status_code == 404


async def test_remove_member(client_ctx, db_session):
    owner_token = await _register_and_login(client_ctx, "owner@example.com")
    member_token = await _register_and_login(client_ctx, "member@example.com")
    member_id = (await client_ctx.get("/api/v1/users/me", headers=_auth(member_token))).json()["id"]
    org_id = (await _create_org(client_ctx, db_session, owner_token, email="owner@example.com", slug="acme"))[
        "id"
    ]
    await client_ctx.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"user_id": member_id, "role_code": "member"},
        headers=_auth(owner_token),
    )

    remove_response = await client_ctx.delete(
        f"/api/v1/organizations/{org_id}/members/{member_id}",
        headers=_auth(owner_token),
    )
    assert remove_response.status_code == 204

    no_longer_member = await client_ctx.get(f"/api/v1/organizations/{org_id}", headers=_auth(member_token))
    assert no_longer_member.status_code == 403


async def test_delete_organization_requires_owner(client_ctx, db_session):
    owner_token = await _register_and_login(client_ctx, "owner@example.com")
    member_token = await _register_and_login(client_ctx, "member@example.com")
    member_id = (await client_ctx.get("/api/v1/users/me", headers=_auth(member_token))).json()["id"]
    org_id = (await _create_org(client_ctx, db_session, owner_token, email="owner@example.com", slug="acme"))[
        "id"
    ]
    await client_ctx.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"user_id": member_id, "role_code": "member"},
        headers=_auth(owner_token),
    )

    forbidden = await client_ctx.delete(f"/api/v1/organizations/{org_id}", headers=_auth(member_token))
    assert forbidden.status_code == 403

    allowed = await client_ctx.delete(f"/api/v1/organizations/{org_id}", headers=_auth(owner_token))
    assert allowed.status_code == 204


# ---------------------------------------------------------------------------
# Resource classification catalog
# ---------------------------------------------------------------------------


async def test_register_and_get_own_resource(client_ctx):
    token = await _register_and_login(client_ctx, "owner@example.com")
    response = await client_ctx.post(
        "/api/v1/resources",
        json={
            "name": "payroll-db",
            "type": "database",
            "tags": {"Confidentiality": "High", "Region": "EU"},
            "is_public": False,
        },
        headers=_auth(token),
    )
    assert response.status_code == 201
    resource_id = response.json()["id"]

    get_response = await client_ctx.get(f"/api/v1/resources/{resource_id}", headers=_auth(token))
    assert get_response.status_code == 200
    assert get_response.json()["tags"] == {"Confidentiality": "High", "Region": "EU"}


async def test_private_resource_hidden_from_other_users(client_ctx):
    owner_token = await _register_and_login(client_ctx, "owner@example.com")
    stranger_token = await _register_and_login(client_ctx, "stranger@example.com")
    resource_id = (
        await client_ctx.post(
            "/api/v1/resources",
            json={"name": "payroll-db", "type": "database", "is_public": False},
            headers=_auth(owner_token),
        )
    ).json()["id"]

    response = await client_ctx.get(f"/api/v1/resources/{resource_id}", headers=_auth(stranger_token))
    assert response.status_code == 404

    listing = await client_ctx.get("/api/v1/resources", headers=_auth(stranger_token))
    assert resource_id not in {r["id"] for r in listing.json()}


async def test_public_resource_visible_to_everyone(client_ctx):
    owner_token = await _register_and_login(client_ctx, "owner@example.com")
    stranger_token = await _register_and_login(client_ctx, "stranger@example.com")
    resource_id = (
        await client_ctx.post(
            "/api/v1/resources",
            json={"name": "public-docs", "type": "bucket", "is_public": True},
            headers=_auth(owner_token),
        )
    ).json()["id"]

    response = await client_ctx.get(f"/api/v1/resources/{resource_id}", headers=_auth(stranger_token))
    assert response.status_code == 200


async def test_register_duplicate_resource_name_rejected(client_ctx):
    token = await _register_and_login(client_ctx, "owner@example.com")
    payload = {"name": "payroll-db", "type": "database"}
    await client_ctx.post("/api/v1/resources", json=payload, headers=_auth(token))
    response = await client_ctx.post("/api/v1/resources", json=payload, headers=_auth(token))
    assert response.status_code == 409


async def test_update_and_delete_resource_requires_owner_or_superuser(client_ctx, db_session):
    owner_token = await _register_and_login(client_ctx, "owner@example.com")
    stranger_token = await _register_and_login(client_ctx, "stranger@example.com")
    admin_token = await _register_and_login(client_ctx, "admin@example.com")
    await _make_superuser(db_session, "admin@example.com")

    resource_id = (
        await client_ctx.post(
            "/api/v1/resources",
            json={"name": "payroll-db", "type": "database", "is_public": True},
            headers=_auth(owner_token),
        )
    ).json()["id"]

    forbidden = await client_ctx.patch(
        f"/api/v1/resources/{resource_id}",
        json={"description": "hijacked"},
        headers=_auth(stranger_token),
    )
    assert forbidden.status_code == 403

    owner_update = await client_ctx.patch(
        f"/api/v1/resources/{resource_id}",
        json={"description": "owner update"},
        headers=_auth(owner_token),
    )
    assert owner_update.status_code == 200
    assert owner_update.json()["description"] == "owner update"

    admin_update = await client_ctx.patch(
        f"/api/v1/resources/{resource_id}",
        json={"description": "admin update"},
        headers=_auth(admin_token),
    )
    assert admin_update.status_code == 200

    stranger_delete = await client_ctx.delete(
        f"/api/v1/resources/{resource_id}", headers=_auth(stranger_token)
    )
    assert stranger_delete.status_code == 403

    owner_delete = await client_ctx.delete(f"/api/v1/resources/{resource_id}", headers=_auth(owner_token))
    assert owner_delete.status_code == 204
