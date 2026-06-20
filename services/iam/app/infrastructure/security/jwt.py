"""Access/refresh token minting and verification (PyJWT, HS256 by default).

Access tokens are stateless and short-lived (`settings.access_token_expire_minutes`).
Refresh tokens are long-lived but tracked durably in Postgres
(``refresh_tokens`` table, see app/infrastructure/db/models/refresh_token.py)
specifically so rotation/reuse can be enforced server-side — the JWT payload
alone is never trusted as proof a refresh token is still valid.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt

from app.core.config import Settings
from app.domain.exceptions import InvalidTokenError

TokenType = Literal["access", "refresh", "mfa_challenge"]

# Hard cap on the embeddable ABAC attribute claim so a large `attributes`
# bag can never blow up the access token to a header-unfriendly size.
_MAX_ATTRS_CLAIM_BYTES = 4 * 1024


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    subject_id: uuid.UUID
    jti: uuid.UUID
    attributes: dict[str, Any]
    tenant_id: str | None
    role: str | None
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
    attributes: dict[str, Any] | None = None,
    tenant_id: str | None = None,
    role: str | None = None,
) -> str:
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": expires_at,
    }
    if attributes:
        if len(json.dumps(attributes)) <= _MAX_ATTRS_CLAIM_BYTES:
            claims["attrs"] = attributes
    # tenant_id/role are claims about the org context this session is bound
    # to (see RefreshToken.organization_id) — absent entirely for a user
    # with no resolved organization at login time, rather than encoded null.
    if tenant_id is not None:
        claims["tenant_id"] = tenant_id
    if role is not None:
        claims["role"] = role
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
            tenant_id=payload.get("tenant_id"),
            role=payload.get("role"),
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


def _decode(
    settings: Settings, token: str, *, expected_type: TokenType
) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(f"Invalid {expected_type} token") from exc

    if payload.get("type") != expected_type:
        raise InvalidTokenError(f"Expected a {expected_type} token")
    return payload
