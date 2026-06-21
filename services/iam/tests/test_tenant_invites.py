"""Tenant invitation flow: POST /api/v1/tenants/{tenant_id}/invites and
POST /api/v1/auth/accept-invite.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from app.infrastructure.db.models.user import User
from sqlalchemy import select


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str, password: str = "Password123!") -> dict:
    resp = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _login(client, email: str, password: str = "Password123!", **kwargs) -> dict:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password, **kwargs})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _login_token(client, email: str, password: str = "Password123!") -> str:
    return (await _login(client, email, password))["access_token"]


async def _set_superuser(db_session, user_id: UUID | str, value: bool) -> None:
    result = await db_session.execute(select(User).where(User.id == UUID(str(user_id))))
    user = result.scalar_one()
    user.is_superuser = value
    db_session.add(user)
    await db_session.commit()


async def _make_superuser(db_session, user_id: UUID | str) -> None:
    await _set_superuser(db_session, user_id, True)


async def _create_org(client, db_session, token: str, *, name: str, slug: str) -> dict:
    """Organization/tenant creation is superuser-only — transiently promotes
    the acting token's user (is_superuser is read fresh from the DB on every
    request, so the existing token works immediately, no re-login needed),
    then demotes them back so the rest of the test still exercises regular
    non-superuser membership/permission behavior."""
    user_id = (await client.get("/api/v1/users/me", headers=_auth(token))).json()["id"]
    await _make_superuser(db_session, user_id)
    resp = await client.post("/api/v1/organizations", json={"name": name, "slug": slug}, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    await _set_superuser(db_session, user_id, False)
    return resp.json()


async def _register_org_owner_scoped(
    client, db_session, email: str, *, name: str, slug: str
) -> tuple[str, dict]:
    """Registers a fresh user, creates an org under them, and returns a
    *re-logged-in* access token — the login before org creation has no
    tenant_id claim yet (the org didn't exist), so a token scoped to the
    new org requires a second login."""
    await _register(client, email)
    org = await _create_org(client, db_session, await _login_token(client, email), name=name, slug=slug)
    scoped_token = await _login_token(client, email)
    return scoped_token, org


class TestCreateInvite:
    @pytest.mark.anyio
    async def test_owner_can_invite_with_full_contract_shape(self, client, db_session):
        await _register(client, "owner@acme.com")
        owner_token = await _login_token(client, "owner@acme.com")
        org = await _create_org(client, db_session, owner_token, name="Acme", slug="acme-co")
        # The org didn't exist yet at the login above, so that token has no
        # tenant_id claim — re-login now that it's the owner's sole org.
        owner_token = await _login_token(client, "owner@acme.com")

        resp = await client.post(
            f"/api/v1/tenants/{org['slug']}/invites",
            json={"email": "newhire@acme.com", "role": "Member"},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["invite_token"]
        assert body["expires_in"] == 86400
        assert body["tenant_id"] == "acme-co"

    @pytest.mark.anyio
    async def test_role_accepts_display_name_or_code(self, client, db_session):
        owner_email = (await _register(client, "owner2@acme.com"))["email"]
        owner_token = await _login_token(client, owner_email)
        org = await _create_org(client, db_session, owner_token, name="Acme2", slug="acme-co-2")
        owner_token = await _login_token(client, owner_email)

        for role_value in ("Member", "member"):
            resp = await client.post(
                f"/api/v1/tenants/{org['slug']}/invites",
                json={"email": f"x-{role_value}@acme.com", "role": role_value},
                headers=_auth(owner_token),
            )
            assert resp.status_code == 201, resp.text

    @pytest.mark.anyio
    async def test_session_not_scoped_to_tenant_returns_403(self, client, db_session):
        """Owner of org A, logged in with a session scoped to org A, cannot
        create an invite for org B even if they're also a member there —
        the access token's own tenant_id claim must match the path."""
        owner_a_email = (await _register(client, "ownerA@test.com"))["email"]
        owner_a_token = await _login_token(client, owner_a_email)
        await _create_org(client, db_session, owner_a_token, name="A", slug="tenant-a")

        owner_a_id = (await client.get("/api/v1/users/me", headers=_auth(owner_a_token))).json()["id"]

        owner_b_email = (await _register(client, "ownerB@test.com"))["email"]
        owner_b_token = await _login_token(client, owner_b_email)
        org_b = await _create_org(client, db_session, owner_b_token, name="B", slug="tenant-b")

        # Make owner_a also a member of org_b, then log them in scoped to org_a.
        await client.post(
            f"/api/v1/organizations/{org_b['id']}/members",
            json={"user_id": owner_a_id, "role_code": "member"},
            headers=_auth(owner_b_token),
        )
        scoped_to_a = await _login(client, owner_a_email, tenant_id="tenant-a")
        token_scoped_to_a = scoped_to_a["access_token"]

        resp = await client.post(
            f"/api/v1/tenants/{org_b['slug']}/invites",
            json={"email": "someone@test.com", "role": "Member"},
            headers=_auth(token_scoped_to_a),
        )
        assert resp.status_code == 403, resp.text

    @pytest.mark.anyio
    async def test_member_without_permission_cannot_invite(self, client, db_session):
        owner_token = await _login_token(client, (await _register(client, "owner3@test.com"))["email"])
        org = await _create_org(client, db_session, owner_token, name="C", slug="tenant-c")

        member_email = (await _register(client, "plainmember@test.com"))["email"]
        member_token = await _login_token(client, member_email)
        member_id = (await client.get("/api/v1/users/me", headers=_auth(member_token))).json()["id"]
        await client.post(
            f"/api/v1/organizations/{org['id']}/members",
            json={"user_id": member_id, "role_code": "member"},
            headers=_auth(owner_token),
        )
        member_scoped = await _login(client, member_email, tenant_id="tenant-c")

        resp = await client.post(
            f"/api/v1/tenants/{org['slug']}/invites",
            json={"email": "x@test.com", "role": "Member"},
            headers=_auth(member_scoped["access_token"]),
        )
        assert resp.status_code == 403, resp.text

    @pytest.mark.anyio
    async def test_superuser_can_invite_without_membership(self, client, db_session):
        super_email = (await _register(client, "super1@test.com"))["email"]
        super_token = await _login_token(client, super_email)
        super_id = (await client.get("/api/v1/users/me", headers=_auth(super_token))).json()["id"]
        await _make_superuser(db_session, super_id)
        super_token = await _login_token(client, super_email)  # re-login: refreshed claims

        owner_token = await _login_token(client, (await _register(client, "owner4@test.com"))["email"])
        org = await _create_org(client, db_session, owner_token, name="D", slug="tenant-d")

        resp = await client.post(
            f"/api/v1/tenants/{org['slug']}/invites",
            json={"email": "x2@test.com", "role": "Member"},
            headers=_auth(super_token),
        )
        assert resp.status_code == 201, resp.text

    @pytest.mark.anyio
    async def test_unknown_tenant_returns_404(self, client):
        owner_token = await _login_token(client, (await _register(client, "owner5@test.com"))["email"])
        resp = await client.post(
            "/api/v1/tenants/does-not-exist/invites",
            json={"email": "x@test.com", "role": "Member"},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 404, resp.text

    @pytest.mark.anyio
    async def test_unknown_role_returns_404(self, client, db_session):
        owner_email = (await _register(client, "owner6@test.com"))["email"]
        owner_token = await _login_token(client, owner_email)
        org = await _create_org(client, db_session, owner_token, name="E", slug="tenant-e")
        owner_token = await _login_token(client, owner_email)
        resp = await client.post(
            f"/api/v1/tenants/{org['slug']}/invites",
            json={"email": "x@test.com", "role": "SuperDuperAdmin"},
            headers=_auth(owner_token),
        )
        assert resp.status_code == 404, resp.text


class TestAcceptInvite:
    @pytest.mark.anyio
    async def test_new_user_accepts_invite_and_can_log_in(self, client, db_session):
        owner_token, org = await _register_org_owner_scoped(
            client, db_session, "owner7@test.com", name="F", slug="tenant-f"
        )
        invite = (
            await client.post(
                f"/api/v1/tenants/{org['slug']}/invites",
                json={"email": "newperson@test.com", "role": "Member"},
                headers=_auth(owner_token),
            )
        ).json()

        resp = await client.post(
            "/api/v1/auth/accept-invite",
            json={
                "invite_token": invite["invite_token"],
                "name": "New Person",
                "password": "StrongPass1!",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["tenant_id"] == "tenant-f"
        assert body["role"] == "Member"
        assert body["status"] == "ACTIVE"

        login_resp = await _login(client, "newperson@test.com", "StrongPass1!")
        assert login_resp["user"]["tenant"]["tenant_id"] == "tenant-f"

    @pytest.mark.anyio
    async def test_invite_token_is_single_use(self, client, db_session):
        owner_token, org = await _register_org_owner_scoped(
            client, db_session, "owner8@test.com", name="G", slug="tenant-g"
        )
        invite = (
            await client.post(
                f"/api/v1/tenants/{org['slug']}/invites",
                json={"email": "reused@test.com", "role": "Member"},
                headers=_auth(owner_token),
            )
        ).json()

        payload = {
            "invite_token": invite["invite_token"],
            "name": "Reused",
            "password": "StrongPass1!",
        }
        first = await client.post("/api/v1/auth/accept-invite", json=payload)
        assert first.status_code == 201, first.text

        replay = await client.post("/api/v1/auth/accept-invite", json=payload)
        assert replay.status_code == 401, replay.text

    @pytest.mark.anyio
    async def test_garbage_token_returns_401(self, client):
        resp = await client.post(
            "/api/v1/auth/accept-invite",
            json={
                "invite_token": "not-a-real-token",
                "name": "X",
                "password": "StrongPass1!",
            },
        )
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_existing_email_is_rejected_not_overwritten(self, client, db_session):
        """Security property: an invite for an email that already has an
        account must never let an unauthenticated caller set that
        account's password."""
        await _register(client, "alreadyexists@test.com", "OriginalPass1!")

        owner_token, org = await _register_org_owner_scoped(
            client, db_session, "owner9@test.com", name="H", slug="tenant-h"
        )
        invite = (
            await client.post(
                f"/api/v1/tenants/{org['slug']}/invites",
                json={"email": "alreadyexists@test.com", "role": "Member"},
                headers=_auth(owner_token),
            )
        ).json()

        resp = await client.post(
            "/api/v1/auth/accept-invite",
            json={
                "invite_token": invite["invite_token"],
                "name": "Attacker-Supplied Name",
                "password": "AttackerPass1!",
            },
        )
        assert resp.status_code == 409, resp.text

        # The original password must still work — it wasn't overwritten.
        original_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "alreadyexists@test.com", "password": "OriginalPass1!"},
        )
        assert original_login.status_code == 200, original_login.text
