"""Policies API tests — POST/GET/PUT/DELETE /api/v1/policies, .../publish,
.../simulate (policies_api_spec).

Distinct from tests/test_hardened_authorization.py's PDP matrix (which
exercises POST /policies/evaluate, the pre-existing, untouched endpoint) —
every test below exercises the new policies_api_spec contract directly:
display_name/type/status/priority/tenant scoping/resource_types/actions/
subjects/metadata, the publish workflow, and the single-policy simulate
dry-run.
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
def unique_name() -> str:
    return f"pol-{uuid4().hex[:8]}"


@pytest.fixture
async def superuser_token(client, db_session, unique_name: str) -> str:
    email = f"{unique_name}@example.com"
    token = await _register_and_login(client, email)
    await _set_superuser(db_session, email, True)
    return token


@pytest.fixture
async def member_token(client) -> str:
    return await _register_and_login(client, f"pol-member-{uuid4().hex[:8]}@example.com")


def _create_payload(**overrides) -> dict:
    body = {
        "name": f"finance-document-access-{uuid4().hex[:8]}",
        "display_name": "Finance Document Access",
        "description": "Controls document access for finance team",
        "type": "ABAC",
        "status": "ACTIVE",
        "priority": 100,
        "effect": "ALLOW",
        "resource_types": ["document", "report"],
        "actions": ["document:read", "document:update"],
        "subjects": {"roles": ["ADMIN", "MEMBER"], "groups": ["finance-team"], "users": ["usr001"]},
        "metadata": {"tags": ["finance", "documents"]},
    }
    body.update(overrides)
    return body


class TestCreatePolicy:
    async def test_create_success(self, client, superuser_token):
        resp = await client.post("/api/v1/policies", json=_create_payload(), headers=_auth(superuser_token))
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["version"] == "v1"
        assert body["status"] == "ACTIVE"
        assert "created_at" in body
        assert set(body.keys()) == {"policy_id", "version", "status", "created_at"}

    async def test_create_defaults(self, client, superuser_token, unique_name):
        resp = await client.post(
            "/api/v1/policies",
            json={
                "name": unique_name,
                "effect": "DENY",
                "resource_types": ["vpn"],
                "actions": ["connect"],
            },
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 201, resp.text
        policy_id = resp.json()["policy_id"]

        fetched = await client.get(f"/api/v1/policies/{policy_id}", headers=_auth(superuser_token))
        body = fetched.json()
        assert body["type"] == "ABAC"
        assert body["priority"] == 0
        assert body["tenant_id"] is None
        assert body["subjects"] == {"roles": [], "groups": [], "users": []}
        assert body["metadata"] == {}

    async def test_create_requires_superuser(self, client, member_token, unique_name):
        resp = await client.post(
            "/api/v1/policies",
            json={
                "name": unique_name,
                "effect": "ALLOW",
                "resource_types": ["document"],
                "actions": ["read"],
            },
            headers=_auth(member_token),
        )
        assert resp.status_code == 403

    async def test_create_duplicate_name_rejected(self, client, superuser_token, unique_name):
        payload = _create_payload(name=unique_name)
        first = await client.post("/api/v1/policies", json=payload, headers=_auth(superuser_token))
        assert first.status_code == 201
        second = await client.post("/api/v1/policies", json=payload, headers=_auth(superuser_token))
        assert second.status_code == 409

    async def test_create_with_malformed_conditions_rejected(self, client, superuser_token, unique_name):
        resp = await client.post(
            "/api/v1/policies",
            json=_create_payload(name=unique_name, conditions={"op": "not-a-real-op", "left": 1, "right": 2}),
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 400

    async def test_create_requires_at_least_one_resource_type_and_action(
        self, client, superuser_token, unique_name
    ):
        resp = await client.post(
            "/api/v1/policies",
            json={"name": unique_name, "effect": "ALLOW", "resource_types": [], "actions": []},
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 422


class TestTenantScoping:
    async def test_create_tenant_scoped_policy(self, client, superuser_token, unique_name):
        org_resp = await client.post(
            "/api/v1/organizations",
            json={"name": "Apple Corp", "slug": f"apple-corp-{uuid4().hex[:8]}"},
            headers=_auth(superuser_token),
        )
        assert org_resp.status_code == 201, org_resp.text
        org_slug = org_resp.json()["slug"]

        created = await client.post(
            "/api/v1/policies",
            json=_create_payload(name=unique_name, tenant_id=org_slug),
            headers=_auth(superuser_token),
        )
        assert created.status_code == 201, created.text
        policy_id = created.json()["policy_id"]

        fetched = await client.get(f"/api/v1/policies/{policy_id}", headers=_auth(superuser_token))
        assert fetched.json()["tenant_id"] == org_slug

        listed = await client.get(
            "/api/v1/policies", params={"tenant_id": org_slug}, headers=_auth(superuser_token)
        )
        assert listed.status_code == 200
        assert any(item["policy_id"] == policy_id for item in listed.json()["items"])


class TestGetListPolicies:
    async def test_get_by_id_full_shape(self, client, superuser_token, unique_name):
        created = await client.post(
            "/api/v1/policies", json=_create_payload(name=unique_name), headers=_auth(superuser_token)
        )
        policy_id = created.json()["policy_id"]

        resp = await client.get(f"/api/v1/policies/{policy_id}", headers=_auth(superuser_token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["policy_id"] == policy_id
        assert body["name"] == unique_name
        assert body["display_name"] == "Finance Document Access"
        assert body["effect"] == "ALLOW"
        assert body["status"] == "ACTIVE"
        assert body["priority"] == 100
        assert body["resource_types"] == ["document", "report"]
        assert body["actions"] == ["document:read", "document:update"]
        assert body["subjects"]["roles"] == ["ADMIN", "MEMBER"]
        assert body["version"] == "v1"

    async def test_get_unknown_returns_404(self, client, superuser_token):
        resp = await client.get(f"/api/v1/policies/{uuid4()}", headers=_auth(superuser_token))
        assert resp.status_code == 404

    async def test_get_requires_superuser(self, client, member_token, superuser_token, unique_name):
        created = await client.post(
            "/api/v1/policies", json=_create_payload(name=unique_name), headers=_auth(superuser_token)
        )
        policy_id = created.json()["policy_id"]
        resp = await client.get(f"/api/v1/policies/{policy_id}", headers=_auth(member_token))
        assert resp.status_code == 403

    async def test_list_pagination_envelope(self, client, superuser_token, unique_name):
        await client.post(
            "/api/v1/policies", json=_create_payload(name=unique_name), headers=_auth(superuser_token)
        )
        resp = await client.get(
            "/api/v1/policies", params={"page": 1, "limit": 20}, headers=_auth(superuser_token)
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["pagination"] == {"page": 1, "limit": 20, "total": body["pagination"]["total"]}
        assert body["pagination"]["total"] >= 1
        item = next(i for i in body["items"] if i["name"] == unique_name)
        assert set(item.keys()) == {"policy_id", "name", "status", "priority", "version"}

    async def test_list_filters_by_status(self, client, superuser_token, unique_name):
        await client.post(
            "/api/v1/policies",
            json=_create_payload(name=unique_name, status="DRAFT"),
            headers=_auth(superuser_token),
        )
        resp = await client.get(
            "/api/v1/policies", params={"status": "DRAFT"}, headers=_auth(superuser_token)
        )
        assert resp.status_code == 200
        assert any(i["name"] == unique_name for i in resp.json()["items"])
        assert all(i["status"] == "DRAFT" for i in resp.json()["items"])


class TestUpdatePolicy:
    async def test_update_success(self, client, superuser_token, unique_name):
        created = await client.post(
            "/api/v1/policies", json=_create_payload(name=unique_name), headers=_auth(superuser_token)
        )
        policy_id = created.json()["policy_id"]

        resp = await client.put(
            f"/api/v1/policies/{policy_id}",
            json={"description": "Updated policy", "priority": 200, "status": "ACTIVE"},
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["policy_id"] == policy_id
        assert body["version"] == "v2"
        assert "updated_at" in body

        fetched = await client.get(f"/api/v1/policies/{policy_id}", headers=_auth(superuser_token))
        fetched_body = fetched.json()
        assert fetched_body["description"] == "Updated policy"
        assert fetched_body["priority"] == 200

    async def test_update_unknown_returns_404(self, client, superuser_token):
        resp = await client.put(
            f"/api/v1/policies/{uuid4()}",
            json={"description": "no such policy"},
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 404

    async def test_update_requires_superuser(self, client, member_token, superuser_token, unique_name):
        created = await client.post(
            "/api/v1/policies", json=_create_payload(name=unique_name), headers=_auth(superuser_token)
        )
        policy_id = created.json()["policy_id"]
        resp = await client.put(
            f"/api/v1/policies/{policy_id}",
            json={"description": "hijacked"},
            headers=_auth(member_token),
        )
        assert resp.status_code == 403


class TestPublishPolicy:
    async def test_publish_success(self, client, superuser_token, unique_name):
        created = await client.post(
            "/api/v1/policies", json=_create_payload(name=unique_name), headers=_auth(superuser_token)
        )
        policy_id = created.json()["policy_id"]

        resp = await client.post(
            f"/api/v1/policies/{policy_id}/publish",
            json={"comment": "Promoting policy to production"},
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["policy_id"] == policy_id
        assert body["version"] == "v2"
        assert body["status"] == "PUBLISHED"

        fetched = await client.get(f"/api/v1/policies/{policy_id}", headers=_auth(superuser_token))
        assert fetched.json()["status"] == "PUBLISHED"

    async def test_publish_requires_superuser(self, client, member_token, superuser_token, unique_name):
        created = await client.post(
            "/api/v1/policies", json=_create_payload(name=unique_name), headers=_auth(superuser_token)
        )
        policy_id = created.json()["policy_id"]
        resp = await client.post(
            f"/api/v1/policies/{policy_id}/publish", json={}, headers=_auth(member_token)
        )
        assert resp.status_code == 403


class TestSimulatePolicy:
    async def test_simulate_matching_condition_allows(self, client, superuser_token, unique_name):
        created = await client.post(
            "/api/v1/policies",
            json=_create_payload(
                name=unique_name,
                conditions={
                    "all": [
                        {"attribute": "user.department", "operator": "eq", "value": "Finance"},
                        {"attribute": "user.clearance_level", "operator": "gte", "value": 3},
                        {"attribute": "context.uses_mfa", "operator": "eq", "value": True},
                    ]
                },
            ),
            headers=_auth(superuser_token),
        )
        assert created.status_code == 201, created.text
        policy_id = created.json()["policy_id"]

        resp = await client.post(
            f"/api/v1/policies/{policy_id}/simulate",
            json={
                "subject": {
                    "user_id": "usr001",
                    "role": "MEMBER",
                    "department": "Finance",
                    "clearance_level": 5,
                },
                "resource": {"type": "document", "tenant_id": "apple_corp"},
                "action": "document:read",
                "context": {"uses_mfa": True, "ip": "203.0.113.10"},
            },
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["decision"] == "ALLOW"
        assert body["matched_policy"] == policy_id
        assert len(body["matched_rules"]) == 3
        assert "evaluation_id" in body

    async def test_simulate_non_matching_condition_denies(self, client, superuser_token, unique_name):
        created = await client.post(
            "/api/v1/policies",
            json=_create_payload(
                name=unique_name,
                conditions={
                    "attribute": "user.department",
                    "operator": "eq",
                    "value": "Finance",
                },
            ),
            headers=_auth(superuser_token),
        )
        policy_id = created.json()["policy_id"]

        resp = await client.post(
            f"/api/v1/policies/{policy_id}/simulate",
            json={
                "subject": {"department": "Sales"},
                "resource": {"type": "document"},
                "action": "document:read",
            },
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 200
        assert resp.json()["decision"] == "DENY"

    async def test_simulate_unknown_policy_returns_404(self, client, superuser_token):
        resp = await client.post(
            f"/api/v1/policies/{uuid4()}/simulate",
            json={"subject": {}, "resource": {}, "action": "document:read"},
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 404


class TestDeletePolicy:
    async def test_delete_success(self, client, superuser_token, unique_name):
        created = await client.post(
            "/api/v1/policies", json=_create_payload(name=unique_name), headers=_auth(superuser_token)
        )
        policy_id = created.json()["policy_id"]

        resp = await client.delete(f"/api/v1/policies/{policy_id}", headers=_auth(superuser_token))
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "message": "Policy deleted"}

        missing = await client.get(f"/api/v1/policies/{policy_id}", headers=_auth(superuser_token))
        assert missing.status_code == 404

    async def test_delete_requires_superuser(self, client, member_token, superuser_token, unique_name):
        created = await client.post(
            "/api/v1/policies", json=_create_payload(name=unique_name), headers=_auth(superuser_token)
        )
        policy_id = created.json()["policy_id"]
        resp = await client.delete(f"/api/v1/policies/{policy_id}", headers=_auth(member_token))
        assert resp.status_code == 403
