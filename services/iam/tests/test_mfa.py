"""TOTP-based MFA: enrollment (setup/confirm), the login challenge/verify
round-trip, recovery codes, and disable.

Unlike the password-reset/invitation token flows, MFA secrets and recovery
codes are returned directly to the authenticated caller (not via a
would-be email), so there's no `debug`-gated response field to deal with
here — see tests/test_password_mgmt.py for that pattern instead.
"""

from __future__ import annotations

from uuid import uuid4

import pyotp
import pytest

_DEFAULT_PASSWORD = "StrongPass1!"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def unique_email() -> str:
    return f"mfa-{uuid4().hex[:8]}@example.com"


@pytest.fixture
async def registered_user(client, unique_email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": unique_email, "password": _DEFAULT_PASSWORD},
    )
    assert resp.status_code == 201, resp.text
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
async def enrolled_mfa(client, registered_user, access_token):
    """Completes setup + confirm; returns (secret, recovery_codes)."""
    setup_resp = await client.post(
        "/api/v1/auth/mfa/setup", headers=_auth(access_token)
    )
    assert setup_resp.status_code == 200, setup_resp.text
    secret = setup_resp.json()["secret"]

    confirm_resp = await client.post(
        "/api/v1/auth/mfa/confirm",
        json={"code": pyotp.TOTP(secret).now()},
        headers=_auth(access_token),
    )
    assert confirm_resp.status_code == 200, confirm_resp.text
    recovery_codes = confirm_resp.json()["recovery_codes"]
    return secret, recovery_codes


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


class TestMfaSetup:
    @pytest.mark.anyio
    async def test_setup_returns_secret_and_otpauth_uri(
        self, client, access_token, registered_user
    ) -> None:
        resp = await client.post("/api/v1/auth/mfa/setup", headers=_auth(access_token))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["secret"]) >= 16
        assert body["otpauth_uri"].startswith("otpauth://totp/")
        assert registered_user.replace("@", "%40") in body["otpauth_uri"]

    @pytest.mark.anyio
    async def test_setup_requires_authentication(self, client) -> None:
        resp = await client.post("/api/v1/auth/mfa/setup")
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_setup_again_before_confirm_replaces_secret(
        self, client, access_token
    ) -> None:
        first = await client.post("/api/v1/auth/mfa/setup", headers=_auth(access_token))
        second = await client.post(
            "/api/v1/auth/mfa/setup", headers=_auth(access_token)
        )
        assert first.json()["secret"] != second.json()["secret"]

        # Confirming with a code from the now-stale first secret fails.
        resp = await client.post(
            "/api/v1/auth/mfa/confirm",
            json={"code": pyotp.TOTP(first.json()["secret"]).now()},
            headers=_auth(access_token),
        )
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_setup_when_already_enabled_returns_409(
        self, client, access_token, enrolled_mfa
    ) -> None:
        resp = await client.post("/api/v1/auth/mfa/setup", headers=_auth(access_token))
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Confirm
# ---------------------------------------------------------------------------


class TestMfaConfirm:
    @pytest.mark.anyio
    async def test_confirm_with_valid_code_enables_mfa_and_returns_recovery_codes(
        self, client, access_token
    ) -> None:
        setup_resp = await client.post(
            "/api/v1/auth/mfa/setup", headers=_auth(access_token)
        )
        secret = setup_resp.json()["secret"]

        resp = await client.post(
            "/api/v1/auth/mfa/confirm",
            json={"code": pyotp.TOTP(secret).now()},
            headers=_auth(access_token),
        )
        assert resp.status_code == 200, resp.text
        codes = resp.json()["recovery_codes"]
        assert len(codes) == 8
        assert len(set(codes)) == 8

    @pytest.mark.anyio
    async def test_confirm_with_wrong_code_returns_401(
        self, client, access_token
    ) -> None:
        await client.post("/api/v1/auth/mfa/setup", headers=_auth(access_token))
        resp = await client.post(
            "/api/v1/auth/mfa/confirm",
            json={"code": "000000"},
            headers=_auth(access_token),
        )
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_confirm_without_setup_returns_400(
        self, client, access_token
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/mfa/confirm",
            json={"code": "123456"},
            headers=_auth(access_token),
        )
        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_confirm_when_already_enabled_returns_409(
        self, client, access_token, enrolled_mfa
    ) -> None:
        secret, _ = enrolled_mfa
        resp = await client.post(
            "/api/v1/auth/mfa/confirm",
            json={"code": pyotp.TOTP(secret).now()},
            headers=_auth(access_token),
        )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Login challenge / verify
# ---------------------------------------------------------------------------


class TestMfaLoginFlow:
    @pytest.mark.anyio
    async def test_login_without_mfa_returns_tokens_directly(
        self, client, registered_user
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": registered_user, "password": _DEFAULT_PASSWORD},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mfa_required"] is False
        assert body["access_token"] is not None

    @pytest.mark.anyio
    async def test_login_with_mfa_enabled_returns_challenge_not_tokens(
        self, client, registered_user, enrolled_mfa
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": registered_user, "password": _DEFAULT_PASSWORD},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mfa_required"] is True
        assert body["access_token"] is None
        assert body["mfa_challenge_token"] is not None

    @pytest.mark.anyio
    async def test_login_verify_with_valid_totp_code_returns_tokens(
        self, client, registered_user, enrolled_mfa
    ) -> None:
        secret, _ = enrolled_mfa
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": registered_user, "password": _DEFAULT_PASSWORD},
        )
        challenge_token = login_resp.json()["mfa_challenge_token"]

        resp = await client.post(
            "/api/v1/auth/mfa/login-verify",
            json={
                "mfa_challenge_token": challenge_token,
                "code": pyotp.TOTP(secret).now(),
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["access_token"] is not None
        assert "refresh_token" in resp.cookies

    @pytest.mark.anyio
    async def test_login_verify_with_recovery_code_consumes_it(
        self, client, registered_user, enrolled_mfa
    ) -> None:
        _, recovery_codes = enrolled_mfa
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": registered_user, "password": _DEFAULT_PASSWORD},
        )
        challenge_token = login_resp.json()["mfa_challenge_token"]

        first_use = await client.post(
            "/api/v1/auth/mfa/login-verify",
            json={
                "mfa_challenge_token": challenge_token,
                "code": recovery_codes[0],
            },
        )
        assert first_use.status_code == 200, first_use.text

        # The same recovery code can't be reused against a fresh challenge.
        second_login = await client.post(
            "/api/v1/auth/login",
            json={"email": registered_user, "password": _DEFAULT_PASSWORD},
        )
        second_challenge = second_login.json()["mfa_challenge_token"]
        replay = await client.post(
            "/api/v1/auth/mfa/login-verify",
            json={
                "mfa_challenge_token": second_challenge,
                "code": recovery_codes[0],
            },
        )
        assert replay.status_code == 401

    @pytest.mark.anyio
    async def test_login_verify_with_wrong_code_returns_401(
        self, client, registered_user, enrolled_mfa
    ) -> None:
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": registered_user, "password": _DEFAULT_PASSWORD},
        )
        challenge_token = login_resp.json()["mfa_challenge_token"]

        resp = await client.post(
            "/api/v1/auth/mfa/login-verify",
            json={"mfa_challenge_token": challenge_token, "code": "000000"},
        )
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_login_verify_with_garbage_challenge_token_returns_401(
        self, client
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/mfa/login-verify",
            json={"mfa_challenge_token": "not-a-real-token", "code": "123456"},
        )
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_access_token_from_password_step_alone_is_never_issued(
        self, client, registered_user, enrolled_mfa
    ) -> None:
        """The whole point of the challenge: a correct password is never
        enough by itself to obtain a usable access token once MFA is on."""
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": registered_user, "password": _DEFAULT_PASSWORD},
        )
        assert resp.json()["access_token"] is None

    @pytest.mark.anyio
    async def test_challenge_token_cannot_be_replayed_after_success(
        self, client, registered_user, enrolled_mfa
    ) -> None:
        """Single-use: even though the JWT itself is still within its own
        TTL, a challenge token already redeemed once must be rejected."""
        secret, _ = enrolled_mfa
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": registered_user, "password": _DEFAULT_PASSWORD},
        )
        challenge_token = login_resp.json()["mfa_challenge_token"]

        first = await client.post(
            "/api/v1/auth/mfa/login-verify",
            json={
                "mfa_challenge_token": challenge_token,
                "code": pyotp.TOTP(secret).now(),
            },
        )
        assert first.status_code == 200, first.text

        replay = await client.post(
            "/api/v1/auth/mfa/login-verify",
            json={
                "mfa_challenge_token": challenge_token,
                "code": pyotp.TOTP(secret).now(),
            },
        )
        assert replay.status_code == 401

    @pytest.mark.anyio
    async def test_challenge_token_locks_after_max_failed_attempts(
        self, client, registered_user, enrolled_mfa
    ) -> None:
        """The 4th attempt against one challenge is rejected outright — even
        with the correct code — once 3 attempts have already been made."""
        secret, _ = enrolled_mfa
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": registered_user, "password": _DEFAULT_PASSWORD},
        )
        challenge_token = login_resp.json()["mfa_challenge_token"]

        for _ in range(3):
            wrong = await client.post(
                "/api/v1/auth/mfa/login-verify",
                json={"mfa_challenge_token": challenge_token, "code": "000000"},
            )
            assert wrong.status_code == 401

        locked = await client.post(
            "/api/v1/auth/mfa/login-verify",
            json={
                "mfa_challenge_token": challenge_token,
                "code": pyotp.TOTP(secret).now(),
            },
        )
        assert locked.status_code == 401
        assert "locked" in locked.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Disable
# ---------------------------------------------------------------------------


class TestMfaDisable:
    @pytest.mark.anyio
    async def test_disable_with_valid_password_and_code_disables_mfa(
        self, client, registered_user, access_token, enrolled_mfa
    ) -> None:
        secret, _ = enrolled_mfa
        resp = await client.post(
            "/api/v1/auth/mfa/disable",
            json={
                "current_password": _DEFAULT_PASSWORD,
                "code": pyotp.TOTP(secret).now(),
            },
            headers=_auth(access_token),
        )
        assert resp.status_code == 204, resp.text

        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": registered_user, "password": _DEFAULT_PASSWORD},
        )
        assert login_resp.json()["mfa_required"] is False
        assert login_resp.json()["access_token"] is not None

    @pytest.mark.anyio
    async def test_disable_with_recovery_code_also_works(
        self, client, access_token, enrolled_mfa
    ) -> None:
        _, recovery_codes = enrolled_mfa
        resp = await client.post(
            "/api/v1/auth/mfa/disable",
            json={"current_password": _DEFAULT_PASSWORD, "code": recovery_codes[0]},
            headers=_auth(access_token),
        )
        assert resp.status_code == 204, resp.text

    @pytest.mark.anyio
    async def test_disable_with_wrong_password_returns_401(
        self, client, access_token, enrolled_mfa
    ) -> None:
        secret, _ = enrolled_mfa
        resp = await client.post(
            "/api/v1/auth/mfa/disable",
            json={
                "current_password": "WrongPassword!",
                "code": pyotp.TOTP(secret).now(),
            },
            headers=_auth(access_token),
        )
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_disable_with_wrong_code_returns_401(
        self, client, access_token, enrolled_mfa
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/mfa/disable",
            json={"current_password": _DEFAULT_PASSWORD, "code": "000000"},
            headers=_auth(access_token),
        )
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_disable_when_not_enabled_returns_400(
        self, client, access_token
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/mfa/disable",
            json={"current_password": _DEFAULT_PASSWORD, "code": "123456"},
            headers=_auth(access_token),
        )
        assert resp.status_code == 400
