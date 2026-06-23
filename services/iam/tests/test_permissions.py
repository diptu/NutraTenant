"""Permission Management API tests — POST/GET/PUT/DELETE /api/v1/permissions,
.../bulk, .../seed, .../search, .../{id}/roles, .../{id}/usage,
.../{id}/enable|disable, .../{id}/audit.

This route was previously an empty stub (no endpoints at all), so there's no
legacy contract to preserve here — every test below exercises the
Permission_API_Specification_Extended.md contract directly.
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
def unique_email() -> str:
    return f"perm-{uuid4().hex[:8]}@example.com"


@pytest.fixture
async def superuser_token(client, db_session, unique_email: str) -> str:
    token = await _register_and_login(client, unique_email)
    await _set_superuser(db_session, unique_email, True)
    return token


@pytest.fixture
async def member_token(client) -> str:
    return await _register_and_login(client, f"perm-member-{uuid4().hex[:8]}@example.com")


@pytest.fixture
async def global_role_id(client, superuser_token: str) -> str:
    resp = await client.post("/api/v1/roles/seed", headers=_auth(superuser_token))
    assert resp.status_code == 200
    return next(r["id"] for r in resp.json() if r["code"] == "guest")


# ---------------------------------------------------------------------------
# Create Permission
# ---------------------------------------------------------------------------


class TestCreatePermission:
    async def test_create_success(self, client, superuser_token):
        resp = await client.post(
            "/api/v1/permissions",
            json={
                "resource": "invoice",
                "action": "approve",
                "description": "Approve invoices",
                "category": "Finance",
                "risk_level": "HIGH",
            },
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["message"] == "Permission created successfully"
        permission = body["permission"]
        assert permission["name"] == "invoice:approve"
        assert permission["resource"] == "invoice"
        assert permission["action"] == "approve"
        assert permission["category"] == "Finance"
        assert permission["risk_level"] == "HIGH"
        assert permission["is_system"] is False
        assert permission["status"] == "ACTIVE"
        assert permission["tenant_id"] is None

    async def test_create_duplicate_returns_409(self, client, superuser_token):
        payload = {"resource": "invoice", "action": "void"}
        first = await client.post("/api/v1/permissions", json=payload, headers=_auth(superuser_token))
        assert first.status_code == 201
        second = await client.post("/api/v1/permissions", json=payload, headers=_auth(superuser_token))
        assert second.status_code == 409

    async def test_create_requires_superuser(self, client, member_token):
        resp = await client.post(
            "/api/v1/permissions",
            json={"resource": "invoice", "action": "read"},
            headers=_auth(member_token),
        )
        assert resp.status_code == 403

    async def test_create_default_risk_level_is_low(self, client, superuser_token):
        resp = await client.post(
            "/api/v1/permissions",
            json={"resource": "report", "action": "export"},
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 201
        assert resp.json()["permission"]["risk_level"] == "LOW"


# ---------------------------------------------------------------------------
# List / Get / Search
# ---------------------------------------------------------------------------


class TestListGetSearchPermissions:
    async def test_list_returns_pagination_envelope(self, client, superuser_token):
        await client.post(
            "/api/v1/permissions",
            json={"resource": "ledger", "action": "read"},
            headers=_auth(superuser_token),
        )
        resp = await client.get(
            "/api/v1/permissions", params={"page": 1, "page_size": 20}, headers=_auth(superuser_token)
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 1
        assert body["page_size"] == 20
        assert body["total"] >= 1
        assert isinstance(body["permissions"], list)

    async def test_list_filters_by_resource(self, client, superuser_token):
        await client.post(
            "/api/v1/permissions",
            json={"resource": "ledger_filter", "action": "read"},
            headers=_auth(superuser_token),
        )
        await client.post(
            "/api/v1/permissions",
            json={"resource": "other_filter", "action": "read"},
            headers=_auth(superuser_token),
        )
        resp = await client.get(
            "/api/v1/permissions",
            params={"resource": "ledger_filter"},
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["permissions"][0]["resource"] == "ledger_filter"

    async def test_get_by_id(self, client, superuser_token):
        created = await client.post(
            "/api/v1/permissions",
            json={"resource": "widget", "action": "create"},
            headers=_auth(superuser_token),
        )
        permission_id = created.json()["permission"]["id"]
        resp = await client.get(f"/api/v1/permissions/{permission_id}", headers=_auth(superuser_token))
        assert resp.status_code == 200
        assert resp.json()["permission"]["id"] == permission_id

    async def test_get_unknown_returns_404(self, client, superuser_token):
        resp = await client.get(f"/api/v1/permissions/{uuid4()}", headers=_auth(superuser_token))
        assert resp.status_code == 404

    async def test_search(self, client, superuser_token):
        await client.post(
            "/api/v1/permissions",
            json={"resource": "searchable_thing", "action": "create"},
            headers=_auth(superuser_token),
        )
        resp = await client.get(
            "/api/v1/permissions/search",
            params={"q": "searchable_thing"},
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert any(r["resource"] == "searchable_thing" for r in results)


# ---------------------------------------------------------------------------
# Update / Delete
# ---------------------------------------------------------------------------


class TestUpdateDeletePermission:
    async def test_update_success(self, client, superuser_token):
        created = await client.post(
            "/api/v1/permissions",
            json={"resource": "doc", "action": "sign"},
            headers=_auth(superuser_token),
        )
        permission_id = created.json()["permission"]["id"]

        resp = await client.put(
            f"/api/v1/permissions/{permission_id}",
            json={"description": "Updated description", "risk_level": "CRITICAL"},
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["message"] == "Permission updated successfully"
        assert body["permission"]["description"] == "Updated description"
        assert body["permission"]["risk_level"] == "CRITICAL"

    async def test_delete_success(self, client, superuser_token):
        created = await client.post(
            "/api/v1/permissions",
            json={"resource": "throwaway", "action": "delete"},
            headers=_auth(superuser_token),
        )
        permission_id = created.json()["permission"]["id"]

        resp = await client.delete(f"/api/v1/permissions/{permission_id}", headers=_auth(superuser_token))
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "message": "Permission deleted successfully"}

        missing = await client.get(f"/api/v1/permissions/{permission_id}", headers=_auth(superuser_token))
        assert missing.status_code == 404

    async def test_delete_system_permission_forbidden(self, client, superuser_token):
        seeded = await client.post(
            "/api/v1/permissions/seed",
            json={"resources": ["sysres"]},
            headers=_auth(superuser_token),
        )
        assert seeded.status_code == 200
        listed = await client.get(
            "/api/v1/permissions", params={"resource": "sysres"}, headers=_auth(superuser_token)
        )
        permission_id = listed.json()["permissions"][0]["id"]

        resp = await client.delete(f"/api/v1/permissions/{permission_id}", headers=_auth(superuser_token))
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Bulk Create / Seed
# ---------------------------------------------------------------------------


class TestBulkAndSeed:
    async def test_bulk_create(self, client, superuser_token):
        resp = await client.post(
            "/api/v1/permissions/bulk",
            json={
                "permissions": [
                    {"resource": "bulkdoc", "action": "create"},
                    {"resource": "bulkdoc", "action": "read"},
                ]
            },
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 200
        assert resp.json() == {"created": 2, "failed": 0}

    async def test_bulk_create_counts_duplicates_as_failed(self, client, superuser_token):
        await client.post(
            "/api/v1/permissions",
            json={"resource": "bulkdup", "action": "create"},
            headers=_auth(superuser_token),
        )
        resp = await client.post(
            "/api/v1/permissions/bulk",
            json={
                "permissions": [
                    {"resource": "bulkdup", "action": "create"},
                    {"resource": "bulkdup", "action": "read"},
                ]
            },
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 200
        assert resp.json() == {"created": 1, "failed": 1}

    async def test_seed_creates_standard_crud_actions(self, client, superuser_token):
        resp = await client.post(
            "/api/v1/permissions/seed",
            json={"resources": ["widgetseed"]},
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 200
        codes = set(resp.json()["created_permissions"])
        assert codes == {
            "widgetseed:create",
            "widgetseed:read",
            "widgetseed:update",
            "widgetseed:delete",
        }

    async def test_seed_is_idempotent(self, client, superuser_token):
        await client.post(
            "/api/v1/permissions/seed",
            json={"resources": ["idempotentseed"]},
            headers=_auth(superuser_token),
        )
        second = await client.post(
            "/api/v1/permissions/seed",
            json={"resources": ["idempotentseed"]},
            headers=_auth(superuser_token),
        )
        assert second.status_code == 200
        assert second.json()["created_permissions"] == []


# ---------------------------------------------------------------------------
# Role assignment
# ---------------------------------------------------------------------------


class TestPermissionRoleAssignment:
    async def test_assign_get_remove_role(self, client, superuser_token, global_role_id):
        created = await client.post(
            "/api/v1/permissions",
            json={"resource": "rolelinked", "action": "create"},
            headers=_auth(superuser_token),
        )
        permission_id = created.json()["permission"]["id"]

        assign = await client.post(
            f"/api/v1/permissions/{permission_id}/roles",
            json={"role_id": global_role_id},
            headers=_auth(superuser_token),
        )
        assert assign.status_code == 200
        assert assign.json() == {"success": True, "message": "Permission assigned successfully"}

        roles_resp = await client.get(
            f"/api/v1/permissions/{permission_id}/roles", headers=_auth(superuser_token)
        )
        assert roles_resp.status_code == 200
        role_ids = [r["id"] for r in roles_resp.json()["roles"]]
        assert global_role_id in role_ids

        remove = await client.delete(
            f"/api/v1/permissions/{permission_id}/roles/{global_role_id}",
            headers=_auth(superuser_token),
        )
        assert remove.status_code == 200
        assert remove.json() == {"success": True}

        roles_after = await client.get(
            f"/api/v1/permissions/{permission_id}/roles", headers=_auth(superuser_token)
        )
        assert global_role_id not in [r["id"] for r in roles_after.json()["roles"]]

    async def test_assign_is_idempotent(self, client, superuser_token, global_role_id):
        created = await client.post(
            "/api/v1/permissions",
            json={"resource": "idempotentlink", "action": "create"},
            headers=_auth(superuser_token),
        )
        permission_id = created.json()["permission"]["id"]

        for _ in range(2):
            resp = await client.post(
                f"/api/v1/permissions/{permission_id}/roles",
                json={"role_id": global_role_id},
                headers=_auth(superuser_token),
            )
            assert resp.status_code == 200

        roles_resp = await client.get(
            f"/api/v1/permissions/{permission_id}/roles", headers=_auth(superuser_token)
        )
        assert len(roles_resp.json()["roles"]) == 1


# ---------------------------------------------------------------------------
# Usage / Enable / Disable / Audit
# ---------------------------------------------------------------------------


class TestUsageLifecycleAudit:
    async def test_usage_reflects_role_assignment(self, client, superuser_token, global_role_id):
        created = await client.post(
            "/api/v1/permissions",
            json={"resource": "usagecheck", "action": "create"},
            headers=_auth(superuser_token),
        )
        permission_id = created.json()["permission"]["id"]

        await client.post(
            f"/api/v1/permissions/{permission_id}/roles",
            json={"role_id": global_role_id},
            headers=_auth(superuser_token),
        )

        usage = await client.get(f"/api/v1/permissions/{permission_id}/usage", headers=_auth(superuser_token))
        assert usage.status_code == 200
        body = usage.json()
        assert body["roles_count"] == 1
        assert "users_count" in body
        assert "policies_count" in body

    async def test_enable_disable(self, client, superuser_token):
        created = await client.post(
            "/api/v1/permissions",
            json={"resource": "togglable", "action": "create"},
            headers=_auth(superuser_token),
        )
        permission_id = created.json()["permission"]["id"]

        disable = await client.patch(
            f"/api/v1/permissions/{permission_id}/disable", headers=_auth(superuser_token)
        )
        assert disable.status_code == 200
        assert disable.json() == {"status": "DISABLED"}

        enable = await client.patch(
            f"/api/v1/permissions/{permission_id}/enable", headers=_auth(superuser_token)
        )
        assert enable.status_code == 200
        assert enable.json() == {"status": "ACTIVE"}

        fetched = await client.get(f"/api/v1/permissions/{permission_id}", headers=_auth(superuser_token))
        assert fetched.json()["permission"]["status"] == "ACTIVE"

    async def test_audit_history_records_lifecycle_events(self, client, superuser_token):
        created = await client.post(
            "/api/v1/permissions",
            json={"resource": "audited", "action": "create"},
            headers=_auth(superuser_token),
        )
        permission_id = created.json()["permission"]["id"]
        await client.put(
            f"/api/v1/permissions/{permission_id}",
            json={"description": "changed"},
            headers=_auth(superuser_token),
        )
        await client.patch(f"/api/v1/permissions/{permission_id}/disable", headers=_auth(superuser_token))

        resp = await client.get(f"/api/v1/permissions/{permission_id}/audit", headers=_auth(superuser_token))
        assert resp.status_code == 200
        events = [e["event"] for e in resp.json()["events"]]
        assert "permission.created" in events
        assert "permission.updated" in events
        assert "permission.disabled" in events
