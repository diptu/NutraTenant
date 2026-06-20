"""Password self-service, coarse RBAC (global roles), the ABAC PDP's
deny-overrides matrix, context-bound conditions, and policy evaluation tracing.

Named distinctly from any legacy test file, following the same pattern as
tests/test_auth_federation.py and tests/test_user_org_resource_management.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.v1.dependencies import get_token_cache, require_global_role
from app.core.config import get_settings
from app.core.context_middleware import is_in_corporate_range
from app.domain.exceptions import ForbiddenError
from app.infrastructure.db.models.password_reset_token import PasswordResetToken
from app.infrastructure.db.models.policy_evaluation_log import PolicyEvaluationLog
from app.infrastructure.db.models.user import User
from app.infrastructure.security.reset_token import hash_reset_token
from app.infrastructure.security.token_cache import InMemoryTokenCache

pytestmark = pytest.mark.anyio

_PASSWORD = "Sup3rSecret!23"


@pytest.fixture
async def client_ctx(app):
    cache = InMemoryTokenCache()
    app.dependency_overrides[get_token_cache] = lambda: cache
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as ac:
        yield ac


@pytest.fixture
def debug_mode(monkeypatch):
    """Forgot-password returns the raw token directly only in debug mode
    (there's no email service in this $0 stack) — see AuthService.request_password_reset."""
    monkeypatch.setenv("DEBUG", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def corporate_network(monkeypatch):
    monkeypatch.setenv("CORPORATE_IP_CIDRS", '["10.0.0.0/8"]')
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "full_name": None},
    )
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
    )
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_superuser(db_session, email: str) -> None:
    user = (
        await db_session.execute(select(User).where(User.email == email))
    ).scalar_one()
    user.is_superuser = True
    await db_session.commit()


async def _seed_roles(client: AsyncClient, admin_token: str) -> dict[str, str]:
    response = await client.post("/api/v1/roles/seed", headers=_auth(admin_token))
    assert response.status_code == 200
    return {r["code"]: r["id"] for r in response.json()}


# ---------------------------------------------------------------------------
# Password management
# ---------------------------------------------------------------------------


async def test_change_password_revokes_old_sessions_and_allows_new_login(client_ctx):
    token = await _register_and_login(client_ctx, "alice@example.com")
    login_for_cookie = await client_ctx.post(
        "/api/v1/auth/login", json={"email": "alice@example.com", "password": _PASSWORD}
    )
    assert login_for_cookie.status_code == 200

    change = await client_ctx.post(
        "/api/v1/auth/change-password",
        json={"current_password": _PASSWORD, "new_password": "NewSecret!456"},
        headers=_auth(token),
    )
    assert change.status_code == 204

    # The refresh cookie from before the change is now dead.
    stale_refresh = await client_ctx.post("/api/v1/auth/refresh")
    assert stale_refresh.status_code == 401

    old_password_login = await client_ctx.post(
        "/api/v1/auth/login", json={"email": "alice@example.com", "password": _PASSWORD}
    )
    assert old_password_login.status_code == 401

    new_password_login = await client_ctx.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "NewSecret!456"},
    )
    assert new_password_login.status_code == 200


async def test_change_password_wrong_current_password_rejected(client_ctx):
    token = await _register_and_login(client_ctx, "alice@example.com")
    response = await client_ctx.post(
        "/api/v1/auth/change-password",
        json={"current_password": "totally-wrong", "new_password": "NewSecret!456"},
        headers=_auth(token),
    )
    assert response.status_code == 401


async def test_forgot_password_unknown_email_same_generic_response(
    client_ctx, debug_mode
):
    response = await client_ctx.post(
        "/api/v1/auth/forgot-password", json={"email": "nobody@example.com"}
    )
    assert response.status_code == 200
    assert response.json()["reset_token"] is None
    assert "message" in response.json()


async def test_forgot_password_returns_token_only_in_debug_mode(client_ctx, debug_mode):
    await _register_and_login(client_ctx, "alice@example.com")
    response = await client_ctx.post(
        "/api/v1/auth/forgot-password", json={"email": "alice@example.com"}
    )
    assert response.status_code == 200
    assert response.json()["reset_token"] is not None


async def test_forgot_password_no_token_leaked_outside_debug_mode(client_ctx):
    await _register_and_login(client_ctx, "alice@example.com")
    response = await client_ctx.post(
        "/api/v1/auth/forgot-password", json={"email": "alice@example.com"}
    )
    assert response.status_code == 200
    assert response.json()["reset_token"] is None


async def test_reset_password_full_flow_then_old_password_fails(client_ctx, debug_mode):
    await _register_and_login(client_ctx, "alice@example.com")
    forgot = await client_ctx.post(
        "/api/v1/auth/forgot-password", json={"email": "alice@example.com"}
    )
    raw_token = forgot.json()["reset_token"]

    reset = await client_ctx.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "NewSecret!456"},
    )
    assert reset.status_code == 204

    old_login = await client_ctx.post(
        "/api/v1/auth/login", json={"email": "alice@example.com", "password": _PASSWORD}
    )
    assert old_login.status_code == 401

    new_login = await client_ctx.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "NewSecret!456"},
    )
    assert new_login.status_code == 200


async def test_reset_password_invalid_token_rejected(client_ctx):
    response = await client_ctx.post(
        "/api/v1/auth/reset-password",
        json={"token": "not-a-real-token", "new_password": "NewSecret!456"},
    )
    assert response.status_code == 401


async def test_reset_password_token_is_single_use(client_ctx, debug_mode):
    await _register_and_login(client_ctx, "alice@example.com")
    raw_token = (
        await client_ctx.post(
            "/api/v1/auth/forgot-password", json={"email": "alice@example.com"}
        )
    ).json()["reset_token"]

    first = await client_ctx.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "NewSecret!456"},
    )
    assert first.status_code == 204

    second = await client_ctx.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "AnotherOne!789"},
    )
    assert second.status_code == 401


async def test_reset_password_expired_token_rejected(
    client_ctx, db_session, debug_mode
):
    await _register_and_login(client_ctx, "alice@example.com")
    raw_token = (
        await client_ctx.post(
            "/api/v1/auth/forgot-password", json={"email": "alice@example.com"}
        )
    ).json()["reset_token"]

    token_row = (
        await db_session.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == hash_reset_token(raw_token)
            )
        )
    ).scalar_one()
    token_row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()

    response = await client_ctx.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "NewSecret!456"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Coarse-grained (global) role management
# ---------------------------------------------------------------------------


async def test_seed_default_roles_is_idempotent(client_ctx, db_session):
    admin_token = await _register_and_login(client_ctx, "admin@example.com")
    await _make_superuser(db_session, "admin@example.com")

    first = await _seed_roles(client_ctx, admin_token)
    assert set(first) == {"admin", "member", "guest"}

    second = await _seed_roles(client_ctx, admin_token)
    assert second == first  # same IDs — nothing duplicated


async def test_seed_roles_requires_superuser(client_ctx):
    token = await _register_and_login(client_ctx, "alice@example.com")
    response = await client_ctx.post("/api/v1/roles/seed", headers=_auth(token))
    assert response.status_code == 403


async def test_create_update_delete_custom_role(client_ctx, db_session):
    admin_token = await _register_and_login(client_ctx, "admin@example.com")
    await _make_superuser(db_session, "admin@example.com")

    create = await client_ctx.post(
        "/api/v1/roles",
        json={
            "name": "Auditor",
            "code": "auditor",
            "description": "Read-only audit access",
        },
        headers=_auth(admin_token),
    )
    assert create.status_code == 201
    role_id = create.json()["id"]

    update = await client_ctx.patch(
        f"/api/v1/roles/{role_id}",
        json={"description": "Updated"},
        headers=_auth(admin_token),
    )
    assert update.status_code == 200
    assert update.json()["description"] == "Updated"

    delete = await client_ctx.delete(
        f"/api/v1/roles/{role_id}", headers=_auth(admin_token)
    )
    assert delete.status_code == 204


async def test_system_role_cannot_be_modified_or_deleted(client_ctx, db_session):
    admin_token = await _register_and_login(client_ctx, "admin@example.com")
    await _make_superuser(db_session, "admin@example.com")
    roles = await _seed_roles(client_ctx, admin_token)

    forbidden_update = await client_ctx.patch(
        f"/api/v1/roles/{roles['admin']}",
        json={"description": "hijacked"},
        headers=_auth(admin_token),
    )
    assert forbidden_update.status_code == 403

    forbidden_delete = await client_ctx.delete(
        f"/api/v1/roles/{roles['admin']}", headers=_auth(admin_token)
    )
    assert forbidden_delete.status_code == 403


async def test_assign_and_revoke_role(client_ctx, db_session):
    admin_token = await _register_and_login(client_ctx, "admin@example.com")
    await _make_superuser(db_session, "admin@example.com")
    roles = await _seed_roles(client_ctx, admin_token)

    bob_token = await _register_and_login(client_ctx, "bob@example.com")
    bob_id = (
        await client_ctx.get("/api/v1/users/me", headers=_auth(bob_token))
    ).json()["id"]

    assign = await client_ctx.post(
        f"/api/v1/roles/{roles['member']}/assignments",
        json={"user_id": bob_id},
        headers=_auth(admin_token),
    )
    assert assign.status_code == 201

    listing = await client_ctx.get(
        f"/api/v1/roles/assignments/{bob_id}", headers=_auth(admin_token)
    )
    assert listing.status_code == 200
    assert {r["role_code"] for r in listing.json()} == {"member"}

    duplicate = await client_ctx.post(
        f"/api/v1/roles/{roles['member']}/assignments",
        json={"user_id": bob_id},
        headers=_auth(admin_token),
    )
    assert duplicate.status_code == 409

    revoke = await client_ctx.delete(
        f"/api/v1/roles/{roles['member']}/assignments/{bob_id}",
        headers=_auth(admin_token),
    )
    assert revoke.status_code == 204

    revoke_again = await client_ctx.delete(
        f"/api/v1/roles/{roles['member']}/assignments/{bob_id}",
        headers=_auth(admin_token),
    )
    assert revoke_again.status_code == 404


async def test_require_global_role_fast_path_guard(client_ctx, db_session):
    """Direct unit-level exercise of the coarse RBAC dependency itself —
    no dedicated HTTP route is gated by it in this milestone, but the
    fast-path check (single indexed lookup, no ABAC evaluation) is real
    and used by anything that adopts it."""
    admin_token = await _register_and_login(client_ctx, "admin@example.com")
    await _make_superuser(db_session, "admin@example.com")
    roles = await _seed_roles(client_ctx, admin_token)

    bob_token = await _register_and_login(client_ctx, "bob@example.com")
    bob_id = (
        await client_ctx.get("/api/v1/users/me", headers=_auth(bob_token))
    ).json()["id"]
    bob = (
        await db_session.execute(select(User).where(User.id == uuid.UUID(bob_id)))
    ).scalar_one()

    checker = require_global_role("member")

    with pytest.raises(ForbiddenError):
        await checker(current_user=bob, session=db_session)

    await client_ctx.post(
        f"/api/v1/roles/{roles['member']}/assignments",
        json={"user_id": bob_id},
        headers=_auth(admin_token),
    )
    await db_session.refresh(bob)
    result = await checker(current_user=bob, session=db_session)
    assert result.id == bob.id


# ---------------------------------------------------------------------------
# ABAC PDP — deny-overrides matrix, conditions, tracing
# ---------------------------------------------------------------------------


async def _create_policy(client: AsyncClient, admin_token: str, **kwargs) -> dict:
    body = {
        "description": None,
        "conditions": None,
        **kwargs,
    }
    response = await client.post(
        "/api/v1/policies", json=body, headers=_auth(admin_token)
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_pdp_default_deny_when_no_policy_matches(client_ctx):
    token = await _register_and_login(client_ctx, "alice@example.com")
    response = await client_ctx.post(
        "/api/v1/policies/evaluate",
        json={"resource_type": "document", "action": "read"},
        headers=_auth(token),
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "deny"
    assert response.json()["matched_policies"] == []


async def test_pdp_allows_when_unconditional_allow_policy_matches(
    client_ctx, db_session
):
    admin_token = await _register_and_login(client_ctx, "admin@example.com")
    await _make_superuser(db_session, "admin@example.com")
    await _create_policy(
        client_ctx,
        admin_token,
        name="allow-read-document",
        effect="allow",
        resource="document",
        action="read",
    )

    token = await _register_and_login(client_ctx, "alice@example.com")
    response = await client_ctx.post(
        "/api/v1/policies/evaluate",
        json={"resource_type": "document", "action": "read"},
        headers=_auth(token),
    )
    assert response.json()["decision"] == "allow"
    assert len(response.json()["matched_policies"]) == 1


async def test_pdp_deny_overrides_conflicting_allow(client_ctx, db_session):
    admin_token = await _register_and_login(client_ctx, "admin@example.com")
    await _make_superuser(db_session, "admin@example.com")
    await _create_policy(
        client_ctx,
        admin_token,
        name="allow-read-document",
        effect="allow",
        resource="document",
        action="read",
    )
    await _create_policy(
        client_ctx,
        admin_token,
        name="deny-read-document",
        effect="deny",
        resource="document",
        action="read",
    )

    token = await _register_and_login(client_ctx, "alice@example.com")
    response = await client_ctx.post(
        "/api/v1/policies/evaluate",
        json={"resource_type": "document", "action": "read"},
        headers=_auth(token),
    )
    assert response.json()["decision"] == "deny"
    assert len(response.json()["matched_policies"]) == 2


async def test_pdp_wildcard_deny_blocks_everything(client_ctx, db_session):
    admin_token = await _register_and_login(client_ctx, "admin@example.com")
    await _make_superuser(db_session, "admin@example.com")
    await _create_policy(
        client_ctx,
        admin_token,
        name="deny-everything",
        effect="deny",
        resource="*",
        action="*",
    )

    token = await _register_and_login(client_ctx, "alice@example.com")
    response = await client_ctx.post(
        "/api/v1/policies/evaluate",
        json={"resource_type": "anything-at-all", "action": "anything-at-all"},
        headers=_auth(token),
    )
    assert response.json()["decision"] == "deny"


async def test_pdp_condition_matches_subject_department_against_resource(
    client_ctx, db_session
):
    admin_token = await _register_and_login(client_ctx, "admin@example.com")
    await _make_superuser(db_session, "admin@example.com")

    alice_token = await _register_and_login(client_ctx, "alice@example.com")
    alice_id = (
        await client_ctx.get("/api/v1/users/me", headers=_auth(alice_token))
    ).json()["id"]
    await client_ctx.patch(
        f"/api/v1/users/{alice_id}/attributes",
        json={"attributes": {"department": "Engineering"}},
        headers=_auth(admin_token),
    )

    await _create_policy(
        client_ctx,
        admin_token,
        name="dept-match-allow",
        effect="allow",
        resource="document",
        action="read",
        conditions={
            "op": "eq",
            "left": {"var": "subject.attributes.department"},
            "right": {"var": "resource.department"},
        },
    )

    matching = await client_ctx.post(
        "/api/v1/policies/evaluate",
        json={
            "resource_type": "document",
            "action": "read",
            "resource_attributes": {"department": "Engineering"},
        },
        headers=_auth(alice_token),
    )
    assert matching.json()["decision"] == "allow"

    non_matching = await client_ctx.post(
        "/api/v1/policies/evaluate",
        json={
            "resource_type": "document",
            "action": "read",
            "resource_attributes": {"department": "Sales"},
        },
        headers=_auth(alice_token),
    )
    assert non_matching.json()["decision"] == "deny"


async def test_pdp_context_bound_corporate_ip_condition(
    client_ctx, db_session, corporate_network
):
    admin_token = await _register_and_login(client_ctx, "admin@example.com")
    await _make_superuser(db_session, "admin@example.com")
    await _create_policy(
        client_ctx,
        admin_token,
        name="corporate-network-only",
        effect="allow",
        resource="vpn",
        action="connect",
        conditions={
            "op": "eq",
            "left": {"var": "context.ip_in_corporate_range"},
            "right": True,
        },
    )

    token = await _register_and_login(client_ctx, "alice@example.com")

    inside = await client_ctx.post(
        "/api/v1/policies/evaluate",
        json={"resource_type": "vpn", "action": "connect"},
        headers={**_auth(token), "X-Forwarded-For": "10.1.2.3"},
    )
    assert inside.json()["decision"] == "allow"
    assert inside.json()["context"]["ip_in_corporate_range"] is True

    outside = await client_ctx.post(
        "/api/v1/policies/evaluate",
        json={"resource_type": "vpn", "action": "connect"},
        headers={**_auth(token), "X-Forwarded-For": "203.0.113.7"},
    )
    assert outside.json()["decision"] == "deny"
    assert outside.json()["context"]["ip_in_corporate_range"] is False


async def test_policy_evaluation_trace_persisted_accurately(client_ctx, db_session):
    admin_token = await _register_and_login(client_ctx, "admin@example.com")
    await _make_superuser(db_session, "admin@example.com")
    policy = await _create_policy(
        client_ctx,
        admin_token,
        name="allow-read-document",
        effect="allow",
        resource="document",
        action="read",
    )

    alice_token = await _register_and_login(client_ctx, "alice@example.com")
    alice_id = (
        await client_ctx.get("/api/v1/users/me", headers=_auth(alice_token))
    ).json()["id"]

    response = await client_ctx.post(
        "/api/v1/policies/evaluate",
        json={"resource_type": "document", "action": "read"},
        headers=_auth(alice_token),
    )
    log_id = response.json()["log_id"]

    log_row = (
        await db_session.execute(
            select(PolicyEvaluationLog).where(
                PolicyEvaluationLog.id == uuid.UUID(log_id)
            )
        )
    ).scalar_one()
    assert str(log_row.user_id) == alice_id
    assert log_row.decision == "allow"
    assert log_row.resource_type == "document"
    assert log_row.action == "read"
    assert log_row.subject_snapshot["id"] == alice_id
    assert log_row.matched_policies[0]["policy_id"] == policy["id"]
    assert log_row.matched_policies[0]["matched"] is True
    assert "ip_address" in log_row.context_snapshot


async def test_create_policy_with_malformed_conditions_rejected(client_ctx, db_session):
    admin_token = await _register_and_login(client_ctx, "admin@example.com")
    await _make_superuser(db_session, "admin@example.com")
    response = await client_ctx.post(
        "/api/v1/policies",
        json={
            "name": "broken",
            "effect": "allow",
            "resource": "document",
            "action": "read",
            "conditions": {"op": "not-a-real-op", "left": 1, "right": 2},
        },
        headers=_auth(admin_token),
    )
    assert response.status_code == 400


async def test_duplicate_policy_name_rejected(client_ctx, db_session):
    admin_token = await _register_and_login(client_ctx, "admin@example.com")
    await _make_superuser(db_session, "admin@example.com")
    await _create_policy(
        client_ctx,
        admin_token,
        name="dup",
        effect="allow",
        resource="document",
        action="read",
    )
    response = await client_ctx.post(
        "/api/v1/policies",
        json={
            "name": "dup",
            "effect": "allow",
            "resource": "document",
            "action": "write",
        },
        headers=_auth(admin_token),
    )
    assert response.status_code == 409


async def test_non_superuser_cannot_manage_policies(client_ctx):
    token = await _register_and_login(client_ctx, "alice@example.com")
    response = await client_ctx.get("/api/v1/policies", headers=_auth(token))
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Pure-function context helpers
# ---------------------------------------------------------------------------


def test_is_in_corporate_range_matches_and_rejects():
    cidrs = ["10.0.0.0/8", "192.168.1.0/24"]
    assert is_in_corporate_range("10.1.2.3", cidrs) is True
    assert is_in_corporate_range("192.168.1.42", cidrs) is True
    assert is_in_corporate_range("203.0.113.7", cidrs) is False
    assert is_in_corporate_range("not-an-ip", cidrs) is False
    assert is_in_corporate_range("10.1.2.3", []) is False
