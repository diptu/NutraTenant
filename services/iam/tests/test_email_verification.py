"""Email verification endpoint tests.

- POST /api/v1/auth/register     now also issues an email-verification
  token; the raw value is only echoed back in the response when
  `debug` is set (same $0-stack convention as forgot-password's
  reset_token — see tests/test_password_mgmt.py).
- POST /api/v1/auth/verify-email (open — single-use token).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.audit import AuditLog
from app.modules.auth.models import EmailVerificationToken
from app.modules.auth.utils.tokens import (
    generate_verification_token,
    hash_verification_token,
)
from sqlalchemy import select

_DEFAULT_PASSWORD = "StrongPass1!"


@pytest.fixture
def unique_email() -> str:
    return f"verify-{uuid4().hex[:8]}@example.com"


@pytest.fixture
def debug_mode(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("DEBUG", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def registered_user(client, unique_email: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": unique_email, "password": _DEFAULT_PASSWORD},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture
async def issued_verification_token(client, unique_email: str, debug_mode) -> tuple[str, str]:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": unique_email, "password": _DEFAULT_PASSWORD},
    )
    assert resp.status_code == 201
    raw_token = resp.json()["verification_token"]
    assert raw_token is not None
    return unique_email, raw_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Register — verification challenge
# ---------------------------------------------------------------------------


class TestRegisterVerificationChallenge:
    @pytest.mark.anyio
    async def test_response_shape(self, registered_user):
        assert registered_user["is_verified"] is False
        assert registered_user["status"] == "PENDING_VERIFICATION"
        assert registered_user["verification_required"] is True
        assert registered_user["verification_method"] == "email"
        assert registered_user["expires_in"] == 900

    @pytest.mark.anyio
    async def test_no_token_leaked_outside_debug_mode(self, registered_user):
        assert registered_user["verification_token"] is None

    @pytest.mark.anyio
    async def test_token_revealed_in_debug_mode(self, issued_verification_token):
        _, raw_token = issued_verification_token
        assert isinstance(raw_token, str) and len(raw_token) > 0

    @pytest.mark.anyio
    async def test_registration_emits_audit_event(self, registered_user, db_session):
        logs = (
            (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "user.registered")))
            .scalars()
            .all()
        )
        assert len(logs) == 1


# ---------------------------------------------------------------------------
# Verify Email
# ---------------------------------------------------------------------------


class TestVerifyEmail:
    @pytest.mark.anyio
    async def test_verify_success(self, client, issued_verification_token):
        _, raw_token = issued_verification_token
        resp = await client.post("/api/v1/auth/verify-email", json={"verification_token": raw_token})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "VERIFIED"
        assert body["message"] == "Email verified successfully"
        assert "verified_at" in body

    @pytest.mark.anyio
    async def test_verify_marks_user_verified(self, client, issued_verification_token):
        email, raw_token = issued_verification_token
        await client.post("/api/v1/auth/verify-email", json={"verification_token": raw_token})

        login = await client.post("/api/v1/auth/login", json={"email": email, "password": _DEFAULT_PASSWORD})
        assert login.status_code == 200
        profile = await client.get("/api/v1/users/me", headers=_auth(login.json()["access_token"]))
        assert profile.json()["email_verified"] is True

    @pytest.mark.anyio
    async def test_verify_token_is_single_use(self, client, issued_verification_token):
        _, raw_token = issued_verification_token
        first = await client.post("/api/v1/auth/verify-email", json={"verification_token": raw_token})
        assert first.status_code == 200

        second = await client.post("/api/v1/auth/verify-email", json={"verification_token": raw_token})
        assert second.status_code == 401

    @pytest.mark.anyio
    async def test_verify_unknown_token_returns_401(self, client):
        resp = await client.post("/api/v1/auth/verify-email", json={"verification_token": "not-a-real-token"})
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_verify_expired_token_returns_401(self, client, registered_user, db_session):
        raw_token, token_hash = generate_verification_token()
        now = datetime.now(UTC)
        db_session.add(
            EmailVerificationToken(
                token_hash=token_hash,
                user_id=uuid.UUID(registered_user["id"]),
                expires_at=now - timedelta(minutes=1),
                created_at=now - timedelta(minutes=20),
            )
        )
        await db_session.commit()

        resp = await client.post("/api/v1/auth/verify-email", json={"verification_token": raw_token})
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_verify_success_emits_audit_event(self, client, issued_verification_token, db_session):
        _, raw_token = issued_verification_token
        await client.post("/api/v1/auth/verify-email", json={"verification_token": raw_token})
        logs = (
            (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "auth.email.verified")))
            .scalars()
            .all()
        )
        assert len(logs) == 1

    @pytest.mark.anyio
    async def test_verify_missing_token_field_returns_422(self, client):
        resp = await client.post("/api/v1/auth/verify-email", json={})
        assert resp.status_code == 422


def test_hash_verification_token_is_deterministic():
    raw_token, token_hash = generate_verification_token()
    assert hash_verification_token(raw_token) == token_hash
