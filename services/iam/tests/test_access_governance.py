"""Tests for /api/v1/access-requests, /access-reviews, /access-approvals
(User and Access APIs Specification) — a tracked-decision-only workflow:
approving/rejecting a request only updates that request's own status, it
never calls into the Role/Permission APIs to actually grant anything.
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
    return f"gov-{uuid4().hex[:8]}@example.com"


@pytest.fixture
async def superuser_token(client, db_session, unique_email: str) -> str:
    token = await _register_and_login(client, unique_email)
    await _set_superuser(db_session, unique_email, True)
    return token


@pytest.fixture
async def requester_token(client) -> str:
    return await _register_and_login(client, f"gov-req-{uuid4().hex[:8]}@example.com")


class TestAccessRequests:
    async def test_create_for_self(self, client, requester_token):
        user_id = (await client.get("/api/v1/users/me", headers=_auth(requester_token))).json()["id"]
        resp = await client.post(
            "/api/v1/access-requests",
            json={
                "user_id": user_id,
                "requested_roles": ["ADMIN"],
                "requested_permissions": ["policy:update"],
                "justification": "Need temporary production access",
            },
            headers=_auth(requester_token),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "PENDING_APPROVAL"
        assert "request_id" in body

    async def test_create_for_other_user_requires_superuser(self, client, requester_token, superuser_token):
        other_id = (await client.get("/api/v1/users/me", headers=_auth(superuser_token))).json()["id"]
        resp = await client.post(
            "/api/v1/access-requests",
            json={"user_id": other_id, "requested_roles": ["ADMIN"]},
            headers=_auth(requester_token),
        )
        assert resp.status_code == 403

    async def test_get_own_request(self, client, requester_token):
        user_id = (await client.get("/api/v1/users/me", headers=_auth(requester_token))).json()["id"]
        created = await client.post(
            "/api/v1/access-requests",
            json={"user_id": user_id, "requested_roles": ["ADMIN"], "justification": "x"},
            headers=_auth(requester_token),
        )
        request_id = created.json()["request_id"]

        resp = await client.get(f"/api/v1/access-requests/{request_id}", headers=_auth(requester_token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["request_id"] == request_id
        assert body["user_id"] == user_id
        assert body["requested_roles"] == ["ADMIN"]
        assert body["status"] == "PENDING_APPROVAL"

    async def test_get_other_users_request_forbidden(self, client, requester_token, superuser_token):
        user_id = (await client.get("/api/v1/users/me", headers=_auth(requester_token))).json()["id"]
        created = await client.post(
            "/api/v1/access-requests",
            json={"user_id": user_id, "requested_roles": ["ADMIN"]},
            headers=_auth(requester_token),
        )
        request_id = created.json()["request_id"]

        other_token = await _register_and_login(client, f"gov-other-{uuid4().hex[:8]}@example.com")
        resp = await client.get(f"/api/v1/access-requests/{request_id}", headers=_auth(other_token))
        assert resp.status_code == 403

    async def test_get_unknown_returns_404(self, client, requester_token):
        resp = await client.get(f"/api/v1/access-requests/{uuid4()}", headers=_auth(requester_token))
        assert resp.status_code == 404


class TestAccessApprovals:
    async def test_approve_updates_request_status_without_granting_rbac(
        self, client, requester_token, superuser_token
    ):
        user_id = (await client.get("/api/v1/users/me", headers=_auth(requester_token))).json()["id"]
        created = await client.post(
            "/api/v1/access-requests",
            json={
                "user_id": user_id,
                "requested_roles": ["ADMIN"],
                "requested_permissions": ["policy:update"],
                "justification": "Need temporary production access",
            },
            headers=_auth(requester_token),
        )
        request_id = created.json()["request_id"]

        approved = await client.post(
            "/api/v1/access-approvals",
            json={"request_id": request_id, "decision": "APPROVED", "comment": "Approved by security team"},
            headers=_auth(superuser_token),
        )
        assert approved.status_code == 201, approved.text
        approval_body = approved.json()
        assert approval_body["status"] == "COMPLETED"
        assert "processed_at" in approval_body

        request_after = await client.get(
            f"/api/v1/access-requests/{request_id}", headers=_auth(requester_token)
        )
        assert request_after.json()["status"] == "APPROVED"

        # No automatic grant: the requester holds no global "ADMIN" role
        # assignment just because their request was approved.
        global_roles = await client.get(
            f"/api/v1/roles/assignments/{user_id}", headers=_auth(superuser_token)
        )
        assert global_roles.status_code == 200
        assert global_roles.json() == []

    async def test_approve_requires_superuser(self, client, requester_token):
        user_id = (await client.get("/api/v1/users/me", headers=_auth(requester_token))).json()["id"]
        created = await client.post(
            "/api/v1/access-requests",
            json={"user_id": user_id, "requested_roles": ["ADMIN"]},
            headers=_auth(requester_token),
        )
        request_id = created.json()["request_id"]

        resp = await client.post(
            "/api/v1/access-approvals",
            json={"request_id": request_id, "decision": "APPROVED"},
            headers=_auth(requester_token),
        )
        assert resp.status_code == 403

    async def test_approve_already_decided_request_returns_409(
        self, client, requester_token, superuser_token
    ):
        user_id = (await client.get("/api/v1/users/me", headers=_auth(requester_token))).json()["id"]
        created = await client.post(
            "/api/v1/access-requests",
            json={"user_id": user_id, "requested_roles": ["ADMIN"]},
            headers=_auth(requester_token),
        )
        request_id = created.json()["request_id"]

        first = await client.post(
            "/api/v1/access-approvals",
            json={"request_id": request_id, "decision": "REJECTED"},
            headers=_auth(superuser_token),
        )
        assert first.status_code == 201

        second = await client.post(
            "/api/v1/access-approvals",
            json={"request_id": request_id, "decision": "APPROVED"},
            headers=_auth(superuser_token),
        )
        assert second.status_code == 409

    async def test_get_approval_by_id(self, client, requester_token, superuser_token):
        user_id = (await client.get("/api/v1/users/me", headers=_auth(requester_token))).json()["id"]
        created = await client.post(
            "/api/v1/access-requests",
            json={"user_id": user_id, "requested_roles": ["ADMIN"]},
            headers=_auth(requester_token),
        )
        request_id = created.json()["request_id"]
        approved = await client.post(
            "/api/v1/access-approvals",
            json={"request_id": request_id, "decision": "APPROVED"},
            headers=_auth(superuser_token),
        )
        approval_id = approved.json()["approval_id"]

        resp = await client.get(f"/api/v1/access-approvals/{approval_id}", headers=_auth(superuser_token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["approval_id"] == approval_id
        assert body["request_id"] == request_id
        assert body["decision"] == "APPROVED"

    async def test_get_unknown_returns_404(self, client, superuser_token):
        resp = await client.get(f"/api/v1/access-approvals/{uuid4()}", headers=_auth(superuser_token))
        assert resp.status_code == 404


class TestAccessReviews:
    async def test_create_tenant_scoped_review(self, client, superuser_token):
        org_resp = await client.post(
            "/api/v1/organizations",
            json={"name": "Apple Corp", "slug": f"apple-corp-{uuid4().hex[:8]}"},
            headers=_auth(superuser_token),
        )
        assert org_resp.status_code == 201, org_resp.text
        org_slug = org_resp.json()["slug"]

        resp = await client.post(
            "/api/v1/access-reviews",
            json={"review_scope": "tenant", "tenant_id": org_slug, "review_type": "QUARTERLY"},
            headers=_auth(superuser_token),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "OPEN"
        review_id = body["review_id"]

        fetched = await client.get(f"/api/v1/access-reviews/{review_id}", headers=_auth(superuser_token))
        assert fetched.status_code == 200
        fetched_body = fetched.json()
        assert fetched_body["review_scope"] == "tenant"
        assert fetched_body["tenant_id"] == org_slug
        assert fetched_body["review_type"] == "QUARTERLY"
        assert fetched_body["status"] == "OPEN"

    async def test_create_requires_superuser(self, client, requester_token):
        resp = await client.post(
            "/api/v1/access-reviews",
            json={"review_scope": "tenant", "review_type": "QUARTERLY"},
            headers=_auth(requester_token),
        )
        assert resp.status_code == 403

    async def test_get_unknown_returns_404(self, client, superuser_token):
        resp = await client.get(f"/api/v1/access-reviews/{uuid4()}", headers=_auth(superuser_token))
        assert resp.status_code == 404
