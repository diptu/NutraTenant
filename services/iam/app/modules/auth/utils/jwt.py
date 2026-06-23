"""Access/refresh token minting and verification (PyJWT, HS256 by default).

Access tokens are stateless and short-lived (`settings.access_token_expire_minutes`).
Refresh tokens are long-lived but tracked durably in Postgres
(``refresh_tokens`` table, see app/auth/models.py) specifically so
rotation/reuse can be enforced server-side — the JWT payload alone is never
trusted as proof a refresh token is still valid.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from app.core.config import Settings
from app.modules.auth.exceptions import InvalidTokenError

TokenType = Literal["access", "refresh", "mfa_challenge"]

# Hard cap on the embeddable ABAC attribute claim so a large `attributes`
# bag can never blow up the access token to a header-unfriendly size.
_MAX_ATTRS_CLAIM_BYTES = 4 * 1024


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    subject_id: uuid.UUID
    jti: uuid.UUID
    attributes: dict[str, Any]
    session_id: uuid.UUID
    is_superuser: bool
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class RefreshTokenClaims:
    subject_id: uuid.UUID
    jti: uuid.UUID
    family_id: uuid.UUID
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class MfaChallengeClaims:
    subject_id: uuid.UUID
    jti: uuid.UUID
    organization_id: uuid.UUID | None
    expires_at: datetime


def create_access_token(
    settings: Settings,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    attributes: dict[str, Any] | None = None,
    is_superuser: bool = False,
) -> str:
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "type": "access",
        "jti": str(uuid.uuid4()),
        # The session (RefreshToken row) this access token was minted
        # alongside — org/role context is resolved dynamically from this
        # at request time (see app.modules.auth.dependencies.get_current_tenant_slug)
        # rather than trusted directly off the token, so it never goes
        # stale between rotations/role changes within one access token's
        # 15-minute lifetime.
        "session_id": str(session_id),
        "iat": now,
        "exp": expires_at,
        # Always present (not omitted on False) so any service decoding
        # this token — including ones without a callback into IAM's own
        # DB — can check superuser status directly off the claim rather
        # than relying on absence meaning False.
        "is_superuser": is_superuser,
    }
    if attributes:
        if len(json.dumps(attributes)) <= _MAX_ATTRS_CLAIM_BYTES:
            claims["attrs"] = attributes
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(
    settings: Settings,
    *,
    user_id: uuid.UUID,
    jti: uuid.UUID,
    family_id: uuid.UUID,
    expires_at: datetime,
) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "type": "refresh",
        "jti": str(jti),
        "fam": str(family_id),
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_mfa_challenge_token(
    settings: Settings, *, user_id: uuid.UUID, organization_id: uuid.UUID | None = None
) -> str:
    """A short-lived, stateless intermediate token issued after password
    verification succeeds but before tokens are minted, when the account
    has MFA enabled — exchanged for real tokens via verify_mfa_and_login.

    Carries the tenant already resolved during the password step (see
    AuthService._resolve_tenant) so the post-MFA token issuance doesn't have
    to re-disambiguate it from the client.
    """
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.mfa_challenge_token_expire_minutes)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "type": "mfa_challenge",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": expires_at,
    }
    if organization_id is not None:
        claims["org_id"] = str(organization_id)
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_mfa_challenge_token(settings: Settings, token: str) -> MfaChallengeClaims:
    payload = _decode(settings, token, expected_type="mfa_challenge")
    try:
        org_id = payload.get("org_id")
        return MfaChallengeClaims(
            subject_id=uuid.UUID(payload["sub"]),
            jti=uuid.UUID(payload["jti"]),
            organization_id=uuid.UUID(org_id) if org_id is not None else None,
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError("Malformed MFA challenge token claims") from exc


def decode_access_token(settings: Settings, token: str) -> AccessTokenClaims:
    payload = _decode(settings, token, expected_type="access")
    try:
        return AccessTokenClaims(
            subject_id=uuid.UUID(payload["sub"]),
            jti=uuid.UUID(payload["jti"]),
            attributes=payload.get("attrs", {}),
            session_id=uuid.UUID(payload["session_id"]),
            is_superuser=payload.get("is_superuser", False),
            issued_at=datetime.fromtimestamp(payload["iat"], tz=UTC),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError("Malformed access token claims") from exc


def decode_refresh_token(settings: Settings, token: str) -> RefreshTokenClaims:
    payload = _decode(settings, token, expected_type="refresh")
    try:
        return RefreshTokenClaims(
            subject_id=uuid.UUID(payload["sub"]),
            jti=uuid.UUID(payload["jti"]),
            family_id=uuid.UUID(payload["fam"]),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError("Malformed refresh token claims") from exc


def _decode(settings: Settings, token: str, *, expected_type: TokenType) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(f"Invalid {expected_type} token") from exc

    if payload.get("type") != expected_type:
        raise InvalidTokenError(f"Expected a {expected_type} token")
    return payload
