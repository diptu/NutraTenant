"""Password Management endpoint tests.

Updated to the current contract:
  - POST /api/v1/auth/change-password   (authenticated, JSON login)
  - POST /api/v1/auth/forgot-password   (open — enumeration-safe; returns the
    raw reset token directly in `debug` mode since there's no email service
    in this $0 stack, instead of mocking one)
  - POST /api/v1/auth/reset-password    (open — single-use token)
  - Audit events checked via the audit_logs table (this codebase logs to the
    DB, not a mockable AuditLogger singleton).

tests/test_hardened_authorization.py already covers the core happy/sad
paths for this surface — this file focuses on validation edge cases
(weak/missing fields) and token tampering that aren't duplicated there.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.infrastructure.db.models.audit_log import AuditLog

_DEFAULT_PASSWORD = "StrongPass1!"
_NEW_PASSWORD = "NewSecurePass99!"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def unique_email() -> str:
    return f"pwmgmt-{uuid4().hex[:8]}@example.com"


@pytest.fixture
def debug_mode(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("DEBUG", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def registered_user(client, unique_email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": unique_email, "password": _DEFAULT_PASSWORD},
    )
    assert resp.status_code == 201
    return unique_email


@pytest.fixture
async def access_token(client, registered_user: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": registered_user, "password": _DEFAULT_PASSWORD},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
async def issued_reset_token(
    client, registered_user: str, debug_mode
) -> tuple[str, str]:
    resp = await client.post(
        "/api/v1/auth/forgot-password", json={"email": registered_user}
    )
    assert resp.status_code == 200
    raw_token = resp.json()["reset_token"]
    assert raw_token is not None
    return registered_user, raw_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Change Password
# ---------------------------------------------------------------------------


class TestChangePassword:
    @pytest.mark.anyio
    async def test_change_password_success_returns_204(self, client, access_token):
        resp = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": _DEFAULT_PASSWORD, "new_password": _NEW_PASSWORD},
            headers=_auth(access_token),
        )
        assert resp.status_code == 204

    @pytest.mark.anyio
    async def test_new_password_accepted_after_change(
        self, client, access_token, registered_user
    ):
        await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": _DEFAULT_PASSWORD, "new_password": _NEW_PASSWORD},
            headers=_auth(access_token),
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": registered_user, "password": _NEW_PASSWORD},
        )
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_old_password_rejected_after_change(
        self, client, access_token, registered_user
    ):
        await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": _DEFAULT_PASSWORD, "new_password": _NEW_PASSWORD},
            headers=_auth(access_token),
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": registered_user, "password": _DEFAULT_PASSWORD},
        )
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_wrong_current_password_returns_401(self, client, access_token):
        resp = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "WrongCurrent1!", "new_password": _NEW_PASSWORD},
            headers=_auth(access_token),
        )
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_unauthenticated_request_returns_401(self, client):
        resp = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": _DEFAULT_PASSWORD, "new_password": _NEW_PASSWORD},
        )
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_weak_new_password_returns_422(self, client, access_token):
        resp = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": _DEFAULT_PASSWORD, "new_password": "short"},
            headers=_auth(access_token),
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_missing_fields_returns_422(self, client, access_token):
        resp = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": _DEFAULT_PASSWORD},
            headers=_auth(access_token),
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Forgot Password
# ---------------------------------------------------------------------------


class TestForgotPassword:
    @pytest.mark.anyio
    async def test_known_email_returns_200(self, client, registered_user):
        resp = await client.post(
            "/api/v1/auth/forgot-password", json={"email": registered_user}
        )
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_unknown_email_also_returns_200(self, client):
        """Enumeration protection: response must be identical for unknown emails."""
        resp = await client.post(
            "/api/v1/auth/forgot-password", json={"email": "ghost@nowhere.example"}
        )
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_response_message_is_generic_for_both_cases(
        self, client, registered_user
    ):
        known_resp = await client.post(
            "/api/v1/auth/forgot-password", json={"email": registered_user}
        )
        unknown_resp = await client.post(
            "/api/v1/auth/forgot-password", json={"email": "ghost@nowhere.example"}
        )
        assert known_resp.json()["message"] == unknown_resp.json()["message"]

    @pytest.mark.anyio
    async def test_no_token_leaked_for_known_user_outside_debug_mode(
        self, client, registered_user
    ):
        resp = await client.post(
            "/api/v1/auth/forgot-password", json={"email": registered_user}
        )
        assert resp.json()["reset_token"] is None

    @pytest.mark.anyio
    async def test_no_token_for_unknown_user_even_in_debug_mode(
        self, client, debug_mode
    ):
        resp = await client.post(
            "/api/v1/auth/forgot-password", json={"email": "ghost@nowhere.example"}
        )
        assert resp.json()["reset_token"] is None

    @pytest.mark.anyio
    async def test_invalid_email_format_returns_422(self, client):
        resp = await client.post(
            "/api/v1/auth/forgot-password", json={"email": "not-an-email"}
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_reset_request_emits_audit_event(
        self, client, registered_user, db_session
    ):
        await client.post(
            "/api/v1/auth/forgot-password", json={"email": registered_user}
        )
        logs = (
            (
                await db_session.execute(
                    select(AuditLog).where(
                        AuditLog.event_type == "auth.password.reset_requested"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(logs) == 1


# ---------------------------------------------------------------------------
# Reset Password
# ---------------------------------------------------------------------------


class TestResetPassword:
    @pytest.mark.anyio
    async def test_valid_token_returns_204(self, client, issued_reset_token):
        _, raw_token = issued_reset_token
        resp = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": raw_token, "new_password": _NEW_PASSWORD},
        )
        assert resp.status_code == 204

    @pytest.mark.anyio
    async def test_can_login_with_new_password_after_reset(
        self, client, issued_reset_token
    ):
        email, raw_token = issued_reset_token
        await client.post(
            "/api/v1/auth/reset-password",
            json={"token": raw_token, "new_password": _NEW_PASSWORD},
        )
        resp = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": _NEW_PASSWORD}
        )
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_old_password_rejected_after_reset(self, client, issued_reset_token):
        email, raw_token = issued_reset_token
        await client.post(
            "/api/v1/auth/reset-password",
            json={"token": raw_token, "new_password": _NEW_PASSWORD},
        )
        resp = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": _DEFAULT_PASSWORD}
        )
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_token_is_single_use(self, client, issued_reset_token):
        _, raw_token = issued_reset_token
        first = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": raw_token, "new_password": _NEW_PASSWORD},
        )
        assert first.status_code == 204

        second = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": raw_token, "new_password": "AnotherPass1!"},
        )
        assert second.status_code == 401

    @pytest.mark.anyio
    async def test_invalid_token_returns_401(self, client):
        resp = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": "completely-fake-token", "new_password": _NEW_PASSWORD},
        )
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_tampered_token_returns_401(self, client, issued_reset_token):
        _, raw_token = issued_reset_token
        tampered = raw_token[:-4] + "XXXX"
        resp = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": tampered, "new_password": _NEW_PASSWORD},
        )
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_weak_new_password_returns_422(self, client, issued_reset_token):
        _, raw_token = issued_reset_token
        resp = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": raw_token, "new_password": "weak"},
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_missing_token_field_returns_422(self, client):
        resp = await client.post(
            "/api/v1/auth/reset-password", json={"new_password": _NEW_PASSWORD}
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_reset_success_emits_audit_event(
        self, client, issued_reset_token, db_session
    ):
        _, raw_token = issued_reset_token
        await client.post(
            "/api/v1/auth/reset-password",
            json={"token": raw_token, "new_password": _NEW_PASSWORD},
        )
        logs = (
            (
                await db_session.execute(
                    select(AuditLog).where(
                        AuditLog.event_type == "auth.password.reset_completed"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(logs) == 1
