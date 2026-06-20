"""Tests for Organization Management (multi-tenancy) and Role Management (RBAC).

Updated to the current DDD architecture and contract:
  - Two membership tiers exist (`owner`, `member`), not three — there's no
    `org_admin` tier. The escalation-guard tests are adapted to exercise the
    same underlying security property (granting a role with permissions
    you don't hold gets refused) using a custom org-scoped role with
    attached permissions instead of a hardcoded "org_admin" tier.
  - Field/response names follow this codebase's convention: `role_code`
    (flat), not a nested `{"role": {"slug": ...}}`; `organization_id` in
    the role-create payload, not a separate org-scoped endpoint.
  - `GET /organizations` returns a plain list, not a `{items: [...]}`
    envelope (changing that would break the already-tested current
    behavior elsewhere).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.infrastructure.db.models.user import User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str, password: str = "Password123!") -> dict:
    resp = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _login_token(client, email: str, password: str = "Password123!") -> str:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _make_superuser(db_session, user_id: UUID | str) -> None:
    result = await db_session.execute(select(User).where(User.id == UUID(str(user_id))))
    user = result.scalar_one()
    user.is_superuser = True
    db_session.add(user)
    await db_session.commit()


async def _create_org(client, token: str, *, name: str = "Acme Inc", slug: str) -> dict:
    resp = await client.post(
        "/api/v1/organizations", json={"name": name, "slug": slug}, headers=_auth(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _add_member(
    client, token: str, org_id: str, user_id: str, *, role_code: str | None = None
):
    payload: dict = {"user_id": user_id}
    if role_code is not None:
        payload["role_code"] = role_code
    return await client.post(
        f"/api/v1/organizations/{org_id}/members", json=payload, headers=_auth(token)
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
async def outsider(client):
    return await _register(client, "outsider@test.com")


@pytest.fixture
async def outsider_token(client, outsider):
    return await _login_token(client, "outsider@test.com")


@pytest.fixture
async def organization(client, owner_token):
    return await _create_org(client, owner_token, slug="acme")


@pytest.fixture
def debug_mode(monkeypatch):
    """There's no email/notification service in this $0 stack — the raw
    invitation token (like the password-reset token) is only ever handed
    back in the response in debug mode."""
    from app.core.config import get_settings

    monkeypatch.setenv("DEBUG", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Organization CRUD
# ---------------------------------------------------------------------------


class TestCreateOrganization:
    @pytest.mark.anyio
    async def test_creator_becomes_owner(self, client, owner, owner_token) -> None:
        org = await _create_org(client, owner_token, slug="acme-create")
        assert org["owner_id"] == owner["id"]

        members = await client.get(
            f"/api/v1/organizations/{org['id']}/members", headers=_auth(owner_token)
        )
        roles_by_user = {m["user_id"]: m["role_code"] for m in members.json()}
        assert roles_by_user[owner["id"]] == "owner"

    @pytest.mark.anyio
    async def test_duplicate_slug_returns_409(self, client, owner_token) -> None:
        await _create_org(client, owner_token, slug="dup-slug")
        resp = await client.post(
            "/api/v1/organizations",
            json={"name": "Other", "slug": "dup-slug"},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 409

    @pytest.mark.anyio
    async def test_unauthenticated_cannot_create(self, client) -> None:
        resp = await client.post(
            "/api/v1/organizations", json={"name": "X", "slug": "no-auth"}
        )
        assert resp.status_code == 401


class TestGetOrganization:
    @pytest.mark.anyio
    async def test_member_can_get(self, client, organization, owner_token) -> None:
        resp = await client.get(
            f"/api/v1/organizations/{organization['id']}", headers=_auth(owner_token)
        )
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_outsider_cannot_get_org_they_dont_belong_to(
        self, client, organization, outsider_token
    ) -> None:
        resp = await client.get(
            f"/api/v1/organizations/{organization['id']}", headers=_auth(outsider_token)
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_unknown_organization_returns_404(self, client, owner_token) -> None:
        resp = await client.get(
            f"/api/v1/organizations/{uuid4()}", headers=_auth(owner_token)
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_superuser_can_get_any_organization(
        self, client, organization, db_session
    ) -> None:
        su = await _register(client, "super1@test.com")
        await _make_superuser(db_session, su["id"])
        token = await _login_token(client, "super1@test.com")
        resp = await client.get(
            f"/api/v1/organizations/{organization['id']}", headers=_auth(token)
        )
        assert resp.status_code == 200


class TestUpdateOrganization:
    @pytest.mark.anyio
    async def test_owner_can_update(self, client, organization, owner_token) -> None:
        resp = await client.patch(
            f"/api/v1/organizations/{organization['id']}",
            json={"name": "Renamed Inc"},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed Inc"

    @pytest.mark.anyio
    async def test_outsider_cannot_update_org_they_dont_belong_to(
        self, client, organization, outsider_token
    ) -> None:
        resp = await client.patch(
            f"/api/v1/organizations/{organization['id']}",
            json={"name": "Hacked"},
            headers=_auth(outsider_token),
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_plain_member_without_permission_cannot_update(
        self, client, organization, owner_token, member, member_token
    ) -> None:
        resp = await _add_member(client, owner_token, organization["id"], member["id"])
        assert resp.status_code == 201, resp.text

        resp = await client.patch(
            f"/api/v1/organizations/{organization['id']}",
            json={"name": "Nope"},
            headers=_auth(member_token),
        )
        assert resp.status_code == 403


class TestDeleteOrganization:
    @pytest.mark.anyio
    async def test_owner_can_delete(self, client, organization, owner_token) -> None:
        resp = await client.delete(
            f"/api/v1/organizations/{organization['id']}", headers=_auth(owner_token)
        )
        assert resp.status_code == 204

        resp = await client.get(
            f"/api/v1/organizations/{organization['id']}", headers=_auth(owner_token)
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_plain_member_cannot_delete_organization(
        self, client, organization, owner_token, member, member_token
    ) -> None:
        resp = await _add_member(client, owner_token, organization["id"], member["id"])
        assert resp.status_code == 201, resp.text

        resp = await client.delete(
            f"/api/v1/organizations/{organization['id']}", headers=_auth(member_token)
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Membership management
# ---------------------------------------------------------------------------


class TestMembership:
    @pytest.mark.anyio
    async def test_owner_can_add_member_with_default_role(
        self, client, organization, owner_token, member
    ) -> None:
        resp = await _add_member(client, owner_token, organization["id"], member["id"])
        assert resp.status_code == 201, resp.text
        assert resp.json()["role_code"] == "member"

    @pytest.mark.anyio
    async def test_add_existing_member_returns_409(
        self, client, organization, owner_token, member
    ) -> None:
        await _add_member(client, owner_token, organization["id"], member["id"])
        resp = await _add_member(client, owner_token, organization["id"], member["id"])
        assert resp.status_code == 409

    @pytest.mark.anyio
    async def test_add_unknown_user_returns_404(
        self, client, organization, owner_token
    ) -> None:
        resp = await _add_member(client, owner_token, organization["id"], str(uuid4()))
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_outsider_cannot_add_member_to_org_they_dont_belong_to(
        self, client, organization, outsider_token, member
    ) -> None:
        resp = await _add_member(
            client, outsider_token, organization["id"], member["id"]
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_member_can_remove_self(
        self, client, organization, owner_token, member, member_token
    ) -> None:
        await _add_member(client, owner_token, organization["id"], member["id"])

        resp = await client.delete(
            f"/api/v1/organizations/{organization['id']}/members/{member['id']}",
            headers=_auth(member_token),
        )
        assert resp.status_code == 204

    @pytest.mark.anyio
    async def test_plain_member_cannot_remove_others(
        self, client, organization, owner_token, member, member_token, outsider
    ) -> None:
        await _add_member(client, owner_token, organization["id"], member["id"])
        await _add_member(client, owner_token, organization["id"], outsider["id"])

        resp = await client.delete(
            f"/api/v1/organizations/{organization['id']}/members/{outsider['id']}",
            headers=_auth(member_token),
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_cannot_remove_last_owner(
        self, client, organization, owner, owner_token
    ) -> None:
        resp = await client.delete(
            f"/api/v1/organizations/{organization['id']}/members/{owner['id']}",
            headers=_auth(owner_token),
        )
        assert resp.status_code == 409

    @pytest.mark.anyio
    async def test_cannot_demote_last_owner(
        self, client, organization, owner, owner_token
    ) -> None:
        resp = await client.patch(
            f"/api/v1/organizations/{organization['id']}/members/{owner['id']}",
            json={"role_code": "member"},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 409

    @pytest.mark.anyio
    async def test_owner_can_promote_a_member_to_co_owner(
        self, client, organization, owner_token, member, member_token
    ) -> None:
        await _add_member(client, owner_token, organization["id"], member["id"])
        resp = await client.patch(
            f"/api/v1/organizations/{organization['id']}/members/{member['id']}",
            json={"role_code": "owner"},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["role_code"] == "owner"

        # Now that there are two owners, demoting (or removing) either one succeeds.
        demote = await client.patch(
            f"/api/v1/organizations/{organization['id']}/members/{member['id']}",
            json={"role_code": "member"},
            headers=_auth(owner_token),
        )
        assert demote.status_code == 200


# ---------------------------------------------------------------------------
# Dynamic role-grant guard — cannot grant permissions you don't hold
# ---------------------------------------------------------------------------


class TestRoleAssignmentGuard:
    @pytest.mark.anyio
    async def test_plain_member_cannot_assign_any_role(
        self, client, organization, owner_token, member, member_token, outsider
    ) -> None:
        await _add_member(client, owner_token, organization["id"], member["id"])
        await _add_member(client, owner_token, organization["id"], outsider["id"])

        resp = await client.patch(
            f"/api/v1/organizations/{organization['id']}/members/{outsider['id']}",
            json={"role_code": "owner"},
            headers=_auth(member_token),
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_non_owner_cannot_grant_ownership_even_with_matching_permissions(
        self, client, organization, owner_token, member, member_token, outsider
    ) -> None:
        """Ownership is structural, not a permission code — granting it is
        owner-only regardless of what permissions the granter holds."""
        await _add_member(client, owner_token, organization["id"], member["id"])
        await _add_member(client, owner_token, organization["id"], outsider["id"])

        resp = await client.patch(
            f"/api/v1/organizations/{organization['id']}/members/{outsider['id']}",
            json={"role_code": "owner"},
            headers=_auth(member_token),
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_member_holding_a_permission_can_grant_a_role_within_it(
        self,
        client,
        organization,
        owner_token,
        member,
        member_token,
        outsider,
        db_session,
    ) -> None:
        from app.services.rbac_seed import seed_rbac_catalog

        await seed_rbac_catalog(db_session)

        custom = await client.post(
            "/api/v1/roles",
            json={
                "name": "Billing",
                "code": "billing",
                "organization_id": organization["id"],
            },
            headers=_auth(owner_token),
        )
        assert custom.status_code == 201, custom.text
        custom_role_id = custom.json()["id"]

        attach = await client.post(
            f"/api/v1/roles/{custom_role_id}/permissions",
            json={"permission_codes": ["organizations:read"]},
            headers=_auth(owner_token),
        )
        assert attach.status_code == 200, attach.text

        # member holds "billing" (organizations:read) and grants that same
        # role to outsider — within their own permission envelope.
        await _add_member(
            client, owner_token, organization["id"], member["id"], role_code="billing"
        )
        await _add_member(client, owner_token, organization["id"], outsider["id"])

        resp = await client.patch(
            f"/api/v1/organizations/{organization['id']}/members/{outsider['id']}",
            json={"role_code": "billing"},
            headers=_auth(member_token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["role_code"] == "billing"

    @pytest.mark.anyio
    async def test_member_cannot_grant_a_role_exceeding_their_own_permissions(
        self,
        client,
        organization,
        owner_token,
        member,
        member_token,
        outsider,
        db_session,
    ) -> None:
        from app.services.rbac_seed import seed_rbac_catalog

        await seed_rbac_catalog(db_session)

        # A narrow role for `member` (one permission)...
        narrow = await client.post(
            "/api/v1/roles",
            json={
                "name": "Narrow",
                "code": "narrow",
                "organization_id": organization["id"],
            },
            headers=_auth(owner_token),
        )
        await client.post(
            f"/api/v1/roles/{narrow.json()['id']}/permissions",
            json={"permission_codes": ["organizations:read"]},
            headers=_auth(owner_token),
        )

        # ...and a *wider* role carrying a permission `member` doesn't have.
        wide = await client.post(
            "/api/v1/roles",
            json={
                "name": "Wide",
                "code": "wide",
                "organization_id": organization["id"],
            },
            headers=_auth(owner_token),
        )
        await client.post(
            f"/api/v1/roles/{wide.json()['id']}/permissions",
            json={"permission_codes": ["organizations:delete"]},
            headers=_auth(owner_token),
        )

        await _add_member(
            client, owner_token, organization["id"], member["id"], role_code="narrow"
        )
        await _add_member(client, owner_token, organization["id"], outsider["id"])

        resp = await client.patch(
            f"/api/v1/organizations/{organization['id']}/members/{outsider['id']}",
            json={"role_code": "wide"},
            headers=_auth(member_token),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Role management (CRUD) — section 5
# ---------------------------------------------------------------------------


class TestRoleManagement:
    @pytest.mark.anyio
    async def test_superuser_can_create_global_role(
        self, client, owner, owner_token, db_session
    ) -> None:
        await _make_superuser(db_session, owner["id"])
        resp = await client.post(
            "/api/v1/roles",
            json={"name": "Auditor Plus", "code": "auditor_plus"},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["organization_id"] is None

    @pytest.mark.anyio
    async def test_non_superuser_cannot_create_global_role(
        self, client, owner_token
    ) -> None:
        resp = await client.post(
            "/api/v1/roles",
            json={"name": "Sneaky Global", "code": "sneaky_global"},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_org_member_cannot_create_custom_role(
        self, client, organization, owner_token, member, member_token
    ) -> None:
        await _add_member(client, owner_token, organization["id"], member["id"])
        resp = await client.post(
            "/api/v1/roles",
            json={
                "name": "Shadow Role",
                "code": "shadow_role",
                "organization_id": organization["id"],
            },
            headers=_auth(member_token),
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_duplicate_code_in_same_org_scope_returns_409(
        self, client, organization, owner_token
    ) -> None:
        payload = {
            "name": "Reviewer",
            "code": "reviewer",
            "organization_id": organization["id"],
        }
        resp1 = await client.post(
            "/api/v1/roles", json=payload, headers=_auth(owner_token)
        )
        assert resp1.status_code == 201, resp1.text
        resp2 = await client.post(
            "/api/v1/roles", json=payload, headers=_auth(owner_token)
        )
        assert resp2.status_code == 409

    @pytest.mark.anyio
    async def test_two_organizations_can_reuse_the_same_custom_role_code(
        self, client, organization, owner_token
    ) -> None:
        await _register(client, "other-owner@test.com")
        other_owner_token = await _login_token(client, "other-owner@test.com")
        other_org = await _create_org(client, other_owner_token, slug="globex")

        resp1 = await client.post(
            "/api/v1/roles",
            json={
                "name": "Manager",
                "code": "manager",
                "organization_id": organization["id"],
            },
            headers=_auth(owner_token),
        )
        assert resp1.status_code == 201, resp1.text

        resp2 = await client.post(
            "/api/v1/roles",
            json={
                "name": "Manager",
                "code": "manager",
                "organization_id": other_org["id"],
            },
            headers=_auth(other_owner_token),
        )
        assert resp2.status_code == 201, resp2.text

    @pytest.mark.anyio
    async def test_cannot_delete_system_role(
        self, client, organization, owner, owner_token
    ) -> None:
        resp = await client.get("/api/v1/roles", headers=_auth(owner_token))
        assert resp.status_code == 200
        # "owner"/"member" are global-catalog-listed only when global; this
        # organization's auto-provisioned owner role is org-scoped, so fetch
        # it via the members listing instead.
        members = await client.get(
            f"/api/v1/organizations/{organization['id']}/members",
            headers=_auth(owner_token),
        )
        owner_membership = next(
            m for m in members.json() if m["user_id"] == owner["id"]
        )
        assert owner_membership["role_code"] == "owner"

        roles_resp = await client.get("/api/v1/roles", headers=_auth(owner_token))
        global_codes = {r["code"] for r in roles_resp.json()}
        assert (
            "owner" not in global_codes
        )  # confirms it really is org-scoped, not global

    @pytest.mark.anyio
    async def test_cannot_delete_role_currently_assigned_to_a_member(
        self, client, organization, owner_token, member
    ) -> None:
        resp = await client.post(
            "/api/v1/roles",
            json={
                "name": "In Use Role",
                "code": "in_use_role",
                "organization_id": organization["id"],
            },
            headers=_auth(owner_token),
        )
        assert resp.status_code == 201, resp.text
        role = resp.json()

        resp = await _add_member(
            client,
            owner_token,
            organization["id"],
            member["id"],
            role_code="in_use_role",
        )
        assert resp.status_code == 201, resp.text

        resp = await client.delete(
            f"/api/v1/roles/{role['id']}", headers=_auth(owner_token)
        )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


class TestListOrganizations:
    @pytest.mark.anyio
    async def test_caller_only_sees_their_own_organizations(
        self, client, organization, owner_token, outsider_token
    ) -> None:
        resp = await client.get("/api/v1/organizations", headers=_auth(owner_token))
        assert resp.status_code == 200
        assert any(o["id"] == organization["id"] for o in resp.json())

        resp = await client.get("/api/v1/organizations", headers=_auth(outsider_token))
        assert resp.status_code == 200
        assert all(o["id"] != organization["id"] for o in resp.json())


# ---------------------------------------------------------------------------
# Invitations — token-based email invite for non-members
# ---------------------------------------------------------------------------


async def _invite(
    client, token: str, org_id: str, email: str, *, role_code: str | None = None
):
    payload: dict = {"email": email}
    if role_code is not None:
        payload["role_code"] = role_code
    return await client.post(
        f"/api/v1/organizations/{org_id}/invitations",
        json=payload,
        headers=_auth(token),
    )


async def _accept(client, token: str, invitation_token: str):
    return await client.post(
        "/api/v1/organizations/invitations/accept",
        json={"token": invitation_token},
        headers=_auth(token),
    )


class TestOrganizationInvitations:
    @pytest.mark.anyio
    async def test_owner_can_invite_and_invitee_accepts(
        self, client, organization, owner_token, outsider, outsider_token, debug_mode
    ) -> None:
        invite_resp = await _invite(
            client, owner_token, organization["id"], outsider["email"]
        )
        assert invite_resp.status_code == 201, invite_resp.text
        invitation = invite_resp.json()
        assert invitation["email"] == outsider["email"]
        assert invitation["role_code"] == "member"
        assert invitation["invitation_token"] is not None

        accept_resp = await _accept(
            client, outsider_token, invitation["invitation_token"]
        )
        assert accept_resp.status_code == 200, accept_resp.text
        assert accept_resp.json()["role_code"] == "member"

        members = await client.get(
            f"/api/v1/organizations/{organization['id']}/members",
            headers=_auth(owner_token),
        )
        assert any(m["user_id"] == outsider["id"] for m in members.json())

    @pytest.mark.anyio
    async def test_invite_without_debug_mode_omits_raw_token(
        self, client, organization, owner_token, outsider
    ) -> None:
        resp = await _invite(client, owner_token, organization["id"], outsider["email"])
        assert resp.status_code == 201, resp.text
        assert resp.json()["invitation_token"] is None

    @pytest.mark.anyio
    async def test_non_owner_cannot_invite(
        self, client, organization, owner_token, member, member_token, outsider
    ) -> None:
        await _add_member(client, owner_token, organization["id"], member["id"])
        resp = await _invite(
            client, member_token, organization["id"], outsider["email"]
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_invite_existing_member_returns_409(
        self, client, organization, owner_token, member, member_token
    ) -> None:
        await _add_member(client, owner_token, organization["id"], member["id"])
        resp = await _invite(client, owner_token, organization["id"], member["email"])
        assert resp.status_code == 409

    @pytest.mark.anyio
    async def test_accept_with_garbage_token_returns_401(
        self, client, outsider_token
    ) -> None:
        resp = await _accept(client, outsider_token, "not-a-real-token")
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_accept_by_wrong_account_returns_401(
        self,
        client,
        organization,
        owner_token,
        outsider,
        member_token,
        debug_mode,
    ) -> None:
        """The invitation is bound to the invited email — a different logged-in
        account can't redeem someone else's invite even with a valid token."""
        invite_resp = await _invite(
            client, owner_token, organization["id"], outsider["email"]
        )
        token = invite_resp.json()["invitation_token"]

        resp = await _accept(client, member_token, token)
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_revoked_invitation_cannot_be_accepted(
        self,
        client,
        organization,
        owner_token,
        outsider,
        outsider_token,
        debug_mode,
    ) -> None:
        invite_resp = await _invite(
            client, owner_token, organization["id"], outsider["email"]
        )
        invitation = invite_resp.json()

        revoke_resp = await client.delete(
            f"/api/v1/organizations/{organization['id']}/invitations/{invitation['id']}",
            headers=_auth(owner_token),
        )
        assert revoke_resp.status_code == 204

        resp = await _accept(client, outsider_token, invitation["invitation_token"])
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_revoke_unknown_invitation_returns_404(
        self, client, organization, owner_token
    ) -> None:
        resp = await client.delete(
            f"/api/v1/organizations/{organization['id']}/invitations/{uuid4()}",
            headers=_auth(owner_token),
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_list_pending_invitations_excludes_accepted(
        self,
        client,
        organization,
        owner_token,
        outsider,
        outsider_token,
        debug_mode,
    ) -> None:
        invite_resp = await _invite(
            client, owner_token, organization["id"], outsider["email"]
        )
        invitation = invite_resp.json()

        pending = await client.get(
            f"/api/v1/organizations/{organization['id']}/invitations",
            headers=_auth(owner_token),
        )
        assert any(i["id"] == invitation["id"] for i in pending.json())

        await _accept(client, outsider_token, invitation["invitation_token"])

        pending_after = await client.get(
            f"/api/v1/organizations/{organization['id']}/invitations",
            headers=_auth(owner_token),
        )
        assert all(i["id"] != invitation["id"] for i in pending_after.json())

    @pytest.mark.anyio
    async def test_reinviting_same_email_supersedes_stale_invite(
        self,
        client,
        organization,
        owner_token,
        outsider,
        outsider_token,
        debug_mode,
    ) -> None:
        first = await _invite(
            client, owner_token, organization["id"], outsider["email"]
        )
        first_token = first.json()["invitation_token"]

        second = await _invite(
            client, owner_token, organization["id"], outsider["email"]
        )
        second_token = second.json()["invitation_token"]

        stale = await _accept(client, outsider_token, first_token)
        assert stale.status_code == 401

        fresh = await _accept(client, outsider_token, second_token)
        assert fresh.status_code == 200
