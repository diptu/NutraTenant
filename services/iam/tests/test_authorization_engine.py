"""
Tests for the authorization engine: JWTContextMiddleware + require_permission
(JWT-embedded permissions, standalone/additive — not applied to any production
route), the permission catalog (seed/assign/remove on roles), and the
org-scoped permission cache.

Updated to the current DDD architecture:
  - No `org_admin` tier — org-scoped role/permission management is owner-only
    (or superuser). The cross-tenant hostile-path tests are adapted accordingly.
  - Role/Permission identity field is `code`, not `slug`; the global "full
    platform catalog" role is `admin`, not `super_admin` (this codebase's own
    role_service.DEFAULT_GLOBAL_ROLES).
  - Permissions are attached to a role via a separate
    `POST /roles/{id}/permissions` call, not inline at role-creation time.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import jwt
import pytest
from app.core.cache import (
    InMemoryPermissionCache,
    RedisPermissionCache,
    get_permission_cache,
    reset_permission_cache,
)
from app.core.config import get_settings
from app.core.jwt_context_middleware import JWTContextMiddleware, require_permission
from app.core.rbac import PLATFORM_PERMISSIONS
from app.core.rbac_seed import seed_rbac_catalog
from app.infrastructure.database.associations import UserOrganizationRole
from app.modules.organizations.org_permissions import get_member_permissions
from app.modules.roles.models import Role
from app.modules.users.models import User
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mint_token(
    sub: str | UUID,
    *,
    permissions: list[str] | None = None,
    token_type: str = "access",
    expires_delta: timedelta = timedelta(minutes=15),
) -> str:
    """Test-only direct minting — production `create_access_token` doesn't
    support embedding arbitrary `permissions`, since no production route
    uses JWT-embedded permissions; this exercises the standalone primitive."""
    settings = get_settings()
    now = datetime.now(UTC)
    claims = {
        "sub": str(sub),
        "type": token_type,
        "permissions": permissions or [],
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


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


async def _set_superuser(db_session, user_id: UUID | str, value: bool) -> None:
    result = await db_session.execute(select(User).where(User.id == UUID(str(user_id))))
    user = result.scalar_one()
    user.is_superuser = value
    db_session.add(user)
    await db_session.commit()


async def _make_superuser(db_session, user_id: UUID | str) -> None:
    await _set_superuser(db_session, user_id, True)


async def _create_org(client, db_session, token: str, *, slug: str) -> dict:
    """Organization creation is superuser-only — transiently promotes the
    acting token's user, then demotes them back so the rest of the test
    still exercises regular non-superuser behavior."""
    user_id = (await client.get("/api/v1/users/me", headers=_auth(token))).json()["id"]
    await _make_superuser(db_session, user_id)
    resp = await client.post(
        "/api/v1/organizations",
        json={"name": "Acme Inc", "slug": slug},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    await _set_superuser(db_session, user_id, False)
    return resp.json()


def _build_protected_app() -> FastAPI:
    """Minimal standalone app exercising JWTContextMiddleware + require_permission
    end-to-end over real HTTP, without touching any production router (the
    production app intentionally doesn't retrofit this onto existing endpoints,
    to avoid changing their behavior).

    Registers the same DomainError -> HTTP translation app.main does — without
    it, InvalidTokenError/ForbiddenError would propagate as raw exceptions
    instead of 401/403, since this standalone app doesn't go through
    app.main.create_app().
    """
    from app.domain.exceptions import DomainError
    from app.main import _domain_error_handler

    app = FastAPI()
    app.add_middleware(JWTContextMiddleware)
    app.add_exception_handler(DomainError, _domain_error_handler)

    @app.get("/protected")
    async def protected(
        claims: dict = Depends(require_permission("users:create")),
    ) -> dict:
        return {"ok": True, "sub": claims["sub"]}

    return app


@pytest.fixture
async def protected_client():
    transport = ASGITransport(app=_build_protected_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def owner(client):
    return await _register(client, "owner@test.com")


@pytest.fixture
async def owner_token(client, owner):
    return await _login_token(client, "owner@test.com")


@pytest.fixture
async def member(client):
    return await _register(client, "member@test.com")


@pytest.fixture
async def member_token(client, member):
    return await _login_token(client, "member@test.com")


@pytest.fixture
async def organization(client, db_session, owner_token):
    return await _create_org(client, db_session, owner_token, slug="acme")


# ---------------------------------------------------------------------------
# JWT validation: middleware + dependency, happy and hostile paths
# ---------------------------------------------------------------------------


class TestJWTValidation:
    @pytest.mark.anyio
    async def test_valid_token_succeeds(self, protected_client) -> None:
        token = _mint_token(uuid4(), permissions=["users:create"])
        resp = await protected_client.get("/protected", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    @pytest.mark.anyio
    async def test_missing_token_returns_401(self, protected_client) -> None:
        resp = await protected_client.get("/protected")
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_garbage_token_returns_401(self, protected_client) -> None:
        resp = await protected_client.get("/protected", headers=_auth("not-a-real-jwt"))
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_expired_token_returns_401(self, protected_client) -> None:
        token = _mint_token(uuid4(), permissions=["users:create"], expires_delta=timedelta(minutes=-5))
        resp = await protected_client.get("/protected", headers=_auth(token))
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_refresh_token_type_rejected_on_access_route(self, protected_client) -> None:
        token = _mint_token(uuid4(), permissions=["users:create"], token_type="refresh")
        resp = await protected_client.get("/protected", headers=_auth(token))
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Permission-based authorization (require_permission dependency)
# ---------------------------------------------------------------------------


class TestPermissionBasedAuthorization:
    @pytest.mark.anyio
    async def test_token_with_required_permission_succeeds(self, protected_client) -> None:
        token = _mint_token(uuid4(), permissions=["users:create", "users:read"])
        resp = await protected_client.get("/protected", headers=_auth(token))
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_token_missing_required_permission_returns_clean_403(self, protected_client) -> None:
        token = _mint_token(uuid4(), permissions=["users:read"])
        resp = await protected_client.get("/protected", headers=_auth(token))
        assert resp.status_code == 403
        assert "users:create" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_token_with_no_permissions_returns_403(self, protected_client) -> None:
        token = _mint_token(uuid4(), permissions=[])
        resp = await protected_client.get("/protected", headers=_auth(token))
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_missing_token_returns_401_not_403(self, protected_client) -> None:
        """Authentication failures must short-circuit before the permission
        check — a missing/bad token is a 401, never a 403."""
        resp = await protected_client.get("/protected")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Permission catalog: seeding (section 6)
# ---------------------------------------------------------------------------


class TestPermissionCatalogSeeding:
    @pytest.mark.anyio
    async def test_seeding_is_idempotent(self, db_session) -> None:
        from app.modules.permissions.models import Permission

        await seed_rbac_catalog(db_session)
        before = (await db_session.execute(select(Permission))).scalars().all()
        await seed_rbac_catalog(db_session)
        after = (await db_session.execute(select(Permission))).scalars().all()
        assert len(before) == len(after)

    @pytest.mark.anyio
    async def test_admin_role_holds_full_platform_catalog(self, db_session) -> None:
        from app.infrastructure.database.associations import RolePermission
        from sqlalchemy.orm import selectinload

        await seed_rbac_catalog(db_session)
        result = await db_session.execute(
            select(Role)
            .where(Role.code == "admin", Role.organization_id.is_(None))
            .options(selectinload(Role.role_permissions).selectinload(RolePermission.permission))
        )
        role = result.scalar_one()
        assert {p.code for p in role.permissions} == set(PLATFORM_PERMISSIONS.values())

    @pytest.mark.anyio
    async def test_guest_role_holds_no_platform_permissions(self, db_session) -> None:
        await seed_rbac_catalog(db_session)
        from app.infrastructure.database.associations import RolePermission
        from sqlalchemy.orm import selectinload

        result = await db_session.execute(
            select(Role)
            .where(Role.code == "guest", Role.organization_id.is_(None))
            .options(selectinload(Role.role_permissions).selectinload(RolePermission.permission))
        )
        role = result.scalar_one_or_none()
        if role is None:
            return
        assert {p.code for p in role.permissions} == set()


# ---------------------------------------------------------------------------
# Permission catalog: assign / remove on roles (section 6) + protection
# ---------------------------------------------------------------------------


class TestRolePermissionAssignment:
    @pytest.mark.anyio
    async def test_superuser_can_assign_permission_to_global_role(
        self, client, owner, owner_token, db_session
    ) -> None:
        await _make_superuser(db_session, owner["id"])
        await seed_rbac_catalog(db_session)
        resp = await client.post(
            "/api/v1/roles",
            json={"name": "Billing", "slug": "billing_global"},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 201, resp.text
        role = resp.json()["role"]

        resp = await client.post(
            f"/api/v1/roles/{role['id']}/permissions",
            json={"permissions": ["users:read"]},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["permissions_count"] == 1

        listed = await client.get(f"/api/v1/roles/{role['id']}/permissions", headers=_auth(owner_token))
        assert "users:read" in {p["name"] for p in listed.json()["permissions"]}

    @pytest.mark.anyio
    async def test_non_superuser_cannot_assign_permission_to_global_role(
        self, client, owner, owner_token, db_session
    ) -> None:
        await _make_superuser(db_session, owner["id"])
        await seed_rbac_catalog(db_session)
        resp = await client.post(
            "/api/v1/roles",
            json={"name": "Billing2", "slug": "billing_global_2"},
            headers=_auth(owner_token),
        )
        role = resp.json()["role"]

        await _register(client, "plain@test.com")
        plain_token = await _login_token(client, "plain@test.com")
        resp = await client.post(
            f"/api/v1/roles/{role['id']}/permissions",
            json={"permissions": ["users:read"]},
            headers=_auth(plain_token),
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_assign_unknown_permission_code_returns_404(
        self, client, owner, owner_token, db_session
    ) -> None:
        await _make_superuser(db_session, owner["id"])
        resp = await client.post(
            "/api/v1/roles",
            json={"name": "Billing3", "slug": "billing_global_3"},
            headers=_auth(owner_token),
        )
        role = resp.json()["role"]

        resp = await client.post(
            f"/api/v1/roles/{role['id']}/permissions",
            json={"permissions": ["does-not-exist:anything"]},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_remove_permission_from_role(self, client, owner, owner_token, db_session) -> None:
        await _make_superuser(db_session, owner["id"])
        await seed_rbac_catalog(db_session)
        resp = await client.post(
            "/api/v1/roles",
            json={"name": "Billing4", "slug": "billing_global_4"},
            headers=_auth(owner_token),
        )
        role = resp.json()["role"]
        await client.post(
            f"/api/v1/roles/{role['id']}/permissions",
            json={"permissions": ["users:read", "users:create"]},
            headers=_auth(owner_token),
        )

        resp = await client.request(
            "DELETE",
            f"/api/v1/roles/{role['id']}/permissions",
            json={"permissions": ["users:read"]},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 200, resp.text

        listed = await client.get(f"/api/v1/roles/{role['id']}/permissions", headers=_auth(owner_token))
        remaining = {p["name"] for p in listed.json()["permissions"]}
        assert "users:read" not in remaining
        assert "users:create" in remaining

    @pytest.mark.anyio
    async def test_cannot_assign_permission_to_system_role(
        self, client, organization, owner_token, db_session
    ) -> None:
        """The org's auto-provisioned "owner" role is a system role
        (is_system=True) — its permissions can't be edited, even by the owner."""
        from app.modules.roles.repositories.sqlalchemy.role_repository import RoleRepository

        await seed_rbac_catalog(db_session)
        owner_role = await RoleRepository(db_session).get_by_code_in_org(
            uuid.UUID(organization["id"]), "owner"
        )
        assert owner_role is not None

        resp = await client.post(
            f"/api/v1/roles/{owner_role.id}/permissions",
            json={"permissions": ["users:read"]},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_org_owner_can_assign_permission_to_org_custom_role(
        self, client, organization, owner_token, db_session
    ) -> None:
        await seed_rbac_catalog(db_session)
        resp = await client.post(
            "/api/v1/roles",
            json={
                "name": "Custom",
                "slug": "custom_role",
                "tenant_id": organization["slug"],
            },
            headers=_auth(owner_token),
        )
        assert resp.status_code == 201, resp.text
        role = resp.json()["role"]

        resp = await client.post(
            f"/api/v1/roles/{role['id']}/permissions",
            json={"permissions": ["organizations:read"]},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 200, resp.text

    @pytest.mark.anyio
    async def test_org_member_cannot_assign_permission_to_org_custom_role(
        self, client, organization, owner_token, member, member_token, db_session
    ) -> None:
        await seed_rbac_catalog(db_session)
        resp = await client.post(
            "/api/v1/roles",
            json={
                "name": "Custom2",
                "slug": "custom_role_2",
                "tenant_id": organization["slug"],
            },
            headers=_auth(owner_token),
        )
        role = resp.json()["role"]

        await client.post(
            f"/api/v1/organizations/{organization['id']}/members",
            json={"user_id": member["id"]},
            headers=_auth(owner_token),
        )
        resp = await client.post(
            f"/api/v1/roles/{role['id']}/permissions",
            json={"permissions": ["organizations:read"]},
            headers=_auth(member_token),
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_outsider_cannot_assign_permission_to_role_in_org_they_dont_belong_to(
        self, client, organization, owner_token, db_session
    ) -> None:
        await seed_rbac_catalog(db_session)
        resp = await client.post(
            "/api/v1/roles",
            json={
                "name": "Custom3",
                "slug": "custom_role_3",
                "tenant_id": organization["slug"],
            },
            headers=_auth(owner_token),
        )
        role = resp.json()["role"]

        await _register(client, "outsider2@test.com")
        outsider_token = await _login_token(client, "outsider2@test.com")
        resp = await client.post(
            f"/api/v1/roles/{role['id']}/permissions",
            json={"permissions": ["organizations:read"]},
            headers=_auth(outsider_token),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Org-scoped permission cache (section 7 — ACL caching)
# ---------------------------------------------------------------------------


class TestPermissionCache:
    @pytest.fixture(autouse=True)
    def _clean_cache(self):
        reset_permission_cache()
        yield
        reset_permission_cache()

    def _member(self, *, permission_codes: set[str], updated_at: datetime) -> UserOrganizationRole:
        # Duck-typed stand-in: get_member_permissions only ever touches
        # .user_id / .role.id / .role.updated_at / .role.permissions[*].code,
        # so a real DB-backed membership isn't needed for this test.
        role = SimpleNamespace(
            id=uuid4(),
            updated_at=updated_at,
            permissions=[SimpleNamespace(code=c) for c in permission_codes],
        )
        return cast("UserOrganizationRole", SimpleNamespace(user_id=uuid4(), role=role))

    @pytest.mark.anyio
    async def test_in_memory_cache_round_trip(self) -> None:
        cache = InMemoryPermissionCache()
        await cache.set("k", {"a", "b"}, ttl_seconds=60)
        assert await cache.get("k") == {"a", "b"}

    @pytest.mark.anyio
    async def test_in_memory_cache_expires(self, monkeypatch) -> None:
        cache = InMemoryPermissionCache()
        clock = {"t": 0.0}
        monkeypatch.setattr("app.core.cache.time.monotonic", lambda: clock["t"])

        await cache.set("k", {"a"}, ttl_seconds=10)
        assert await cache.get("k") == {"a"}

        clock["t"] = 11.0
        assert await cache.get("k") is None

    @pytest.mark.anyio
    async def test_cache_hit_avoids_recomputation(self) -> None:
        cache = InMemoryPermissionCache()
        now = datetime.now(UTC)
        organization_id = uuid4()
        member = self._member(permission_codes={"organizations:read"}, updated_at=now)

        first = await get_member_permissions(organization_id, member, cache=cache)
        assert first == {"organizations:read"}

        # Mutate the in-memory relationship *without* bumping updated_at —
        # the cache key is unchanged, so the stale (cached) value wins.
        member.role.permissions = []  # type: ignore[misc]
        second = await get_member_permissions(organization_id, member, cache=cache)
        assert second == {"organizations:read"}

    @pytest.mark.anyio
    async def test_role_version_change_busts_the_cache(self) -> None:
        cache = InMemoryPermissionCache()
        now = datetime.now(UTC)
        organization_id = uuid4()
        member = self._member(permission_codes={"organizations:read"}, updated_at=now)

        first = await get_member_permissions(organization_id, member, cache=cache)
        assert first == {"organizations:read"}

        member.role.permissions = []  # type: ignore[misc]
        member.role.updated_at = now + timedelta(seconds=1)
        second = await get_member_permissions(organization_id, member, cache=cache)
        assert second == set()

    @pytest.mark.anyio
    async def test_redis_construction_failure_falls_back_to_in_memory(self, monkeypatch) -> None:
        monkeypatch.setattr(get_settings(), "redis_url", "not a valid redis url")
        cache = get_permission_cache()
        assert isinstance(cache, InMemoryPermissionCache)

    @pytest.mark.anyio
    async def test_redis_url_configured_builds_redis_backend(self, monkeypatch) -> None:
        monkeypatch.setattr(get_settings(), "redis_url", "redis://localhost:6379/0")
        cache = get_permission_cache()
        assert isinstance(cache, RedisPermissionCache)


# ---------------------------------------------------------------------------
# Sanity: cross-tenant administration attempt produces a clean 403, not a
# 500 or a silent 200 — explicit hostile-path requirement.
# ---------------------------------------------------------------------------


class TestHostileCrossTenantAdministration:
    @pytest.mark.anyio
    async def test_outsider_invoking_cross_tenant_admin_action_gets_clean_403(
        self, client, organization
    ) -> None:
        await _register(client, "outsider3@test.com")
        outsider_token = await _login_token(client, "outsider3@test.com")
        resp = await client.patch(
            f"/api/v1/organizations/{organization['id']}",
            json={"name": str(uuid.uuid4())},
            headers=_auth(outsider_token),
        )
        assert resp.status_code == 403
        assert "detail" in resp.json()
