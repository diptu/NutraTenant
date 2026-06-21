"""GET /api/v1/users/{user_id}/sessions and DELETE .../sessions/{session_id}
— each row in `refresh_tokens` *is* a session record (see
app.infrastructure.db.models.refresh_token.RefreshToken and
AuthService.list_sessions/revoke_session).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from app.infrastructure.db.models.user import User
from sqlalchemy import select

pytestmark = pytest.mark.anyio


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str, password: str = "Password123!") -> dict:
    resp = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _login(client, email: str, password: str = "Password123!") -> dict:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _login_token(client, email: str, password: str = "Password123!") -> str:
    return (await _login(client, email, password))["access_token"]


async def _make_superuser(db_session, user_id: str) -> None:
    result = await db_session.execute(select(User).where(User.id == UUID(str(user_id))))
    user = result.scalar_one()
    user.is_superuser = True
    db_session.add(user)
    await db_session.commit()


async def _superuser_token(client, db_session, email: str) -> str:
    await _register(client, email)
    token = await _login_token(client, email)
    user_id = (await client.get("/api/v1/users/me", headers=_auth(token))).json()["id"]
    await _make_superuser(db_session, user_id)
    return await _login_token(client, email)


class TestListUserSessions:
    async def test_self_can_list_own_sessions(self, client):
        email = "alice-sess@test.com"
        await _register(client, email)
        await _login_token(client, email)
        await _login_token(client, email)  # two sessions now

        token = await _login_token(client, email)  # a third, used to call the endpoint
        user_id = (await client.get("/api/v1/users/me", headers=_auth(token))).json()["id"]

        resp = await client.get(f"/api/v1/users/{user_id}/sessions", headers=_auth(token))
        assert resp.status_code == 200, resp.text
        sessions = resp.json()["sessions"]
        assert len(sessions) == 3
        for entry in sessions:
            assert entry["session_id"].startswith("sess_")
            assert entry["device"]
            assert entry["issued_at"]
            assert entry["expires_at"]

    async def test_other_user_forbidden_without_superuser(self, client):
        alice_token = await _login_token(client, (await _register(client, "alice-sess2@test.com"))["email"])
        alice_id = (await client.get("/api/v1/users/me", headers=_auth(alice_token))).json()["id"]
        bob_token = await _login_token(client, (await _register(client, "bob-sess2@test.com"))["email"])

        resp = await client.get(f"/api/v1/users/{alice_id}/sessions", headers=_auth(bob_token))
        assert resp.status_code == 403

    async def test_superuser_can_list_any_users_sessions(self, client, db_session):
        super_token = await _superuser_token(client, db_session, "root-sess@test.com")
        alice_token = await _login_token(client, (await _register(client, "alice-sess3@test.com"))["email"])
        alice_id = (await client.get("/api/v1/users/me", headers=_auth(alice_token))).json()["id"]

        resp = await client.get(f"/api/v1/users/{alice_id}/sessions", headers=_auth(super_token))
        assert resp.status_code == 200
        assert len(resp.json()["sessions"]) == 1


class TestRevokeUserSession:
    async def test_self_can_revoke_own_session(self, client):
        email = "alice-sess4@test.com"
        await _register(client, email)
        stale = await _login(client, email)
        stale_session_id = stale["session"]["session_id"]

        token = await _login_token(client, email)
        user_id = (await client.get("/api/v1/users/me", headers=_auth(token))).json()["id"]

        resp = await client.delete(
            f"/api/v1/users/{user_id}/sessions/{stale_session_id}", headers=_auth(token)
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success": True, "message": "Session revoked"}

        remaining = await client.get(f"/api/v1/users/{user_id}/sessions", headers=_auth(token))
        remaining_ids = {s["session_id"] for s in remaining.json()["sessions"]}
        assert stale_session_id not in remaining_ids

    async def test_revoking_again_returns_404(self, client):
        email = "alice-sess5@test.com"
        await _register(client, email)
        first = await _login(client, email)
        session_id = first["session"]["session_id"]
        token = first["access_token"]
        user_id = (await client.get("/api/v1/users/me", headers=_auth(token))).json()["id"]

        first_revoke = await client.delete(
            f"/api/v1/users/{user_id}/sessions/{session_id}", headers=_auth(token)
        )
        assert first_revoke.status_code == 200

        second_revoke = await client.delete(
            f"/api/v1/users/{user_id}/sessions/{session_id}", headers=_auth(token)
        )
        assert second_revoke.status_code == 404

    async def test_unknown_session_id_returns_404(self, client):
        token = await _login_token(client, (await _register(client, "alice-sess6@test.com"))["email"])
        user_id = (await client.get("/api/v1/users/me", headers=_auth(token))).json()["id"]

        resp = await client.delete(
            f"/api/v1/users/{user_id}/sessions/sess_{uuid4()}", headers=_auth(token)
        )
        assert resp.status_code == 404

    async def test_cannot_revoke_another_users_session(self, client):
        alice_token = await _login_token(client, (await _register(client, "alice-sess7@test.com"))["email"])
        alice = await _login(client, "alice-sess7@test.com")
        alice_session_id = alice["session"]["session_id"]
        alice_id = (await client.get("/api/v1/users/me", headers=_auth(alice_token))).json()["id"]

        bob_token = await _login_token(client, (await _register(client, "bob-sess7@test.com"))["email"])

        # Bob can't even address alice's user_id without superuser ...
        forbidden = await client.delete(
            f"/api/v1/users/{alice_id}/sessions/{alice_session_id}", headers=_auth(bob_token)
        )
        assert forbidden.status_code == 403

    async def test_superuser_can_revoke_anyones_session(self, client, db_session):
        super_token = await _superuser_token(client, db_session, "root-sess8@test.com")
        alice_login = await _login(client, (await _register(client, "alice-sess8@test.com"))["email"])
        alice_token = alice_login["access_token"]
        alice_session_id = alice_login["session"]["session_id"]
        alice_id = (await client.get("/api/v1/users/me", headers=_auth(alice_token))).json()["id"]

        resp = await client.delete(
            f"/api/v1/users/{alice_id}/sessions/{alice_session_id}", headers=_auth(super_token)
        )
        assert resp.status_code == 200
