"""Response models for the auth + Google federation endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

__all__ = [
    "AcceptInviteResponse",
    "ForgotPasswordResponse",
    "GoogleAuthorizeResponse",
    "LinksOut",
    "LoginRoleOut",
    "LoginTenantOut",
    "LoginUserOut",
    "MfaConfirmResponse",
    "MfaSetupResponse",
    "RegisterResponse",
    "SessionOut",
    "SwitchTenantResponse",
    "TokenResponse",
    "VerifyEmailResponse",
]


class RegisterResponse(BaseModel):
    """POST /auth/register's response — Common User Object fields plus the
    email-verification challenge. ``verification_token`` is only non-None
    when ``settings.debug`` is set (mirrors ForgotPasswordResponse.reset_token
    — there's no email/notification provider wired up in this $0 stack)."""

    id: uuid.UUID
    email: str
    full_name: str | None
    is_active: bool
    is_verified: bool
    is_superuser: bool
    attributes: dict[str, Any]
    status: str = "PENDING_VERIFICATION"
    verification_required: bool = True
    verification_method: str = "email"
    verification_token: str | None = None
    expires_in: int | None = None


class SessionOut(BaseModel):
    session_id: str
    issued_at: datetime
    expires_at: datetime
    ip_address: str | None
    device: str
    last_login: datetime | None


class LoginTenantOut(BaseModel):
    """Like app.api.v1.users.responses.TenantOut, minus `tenant_id` (the org
    slug) — that's already the JWT access token's own `tenant_id` claim, so
    repeating it here would just be the same value rendered twice. `id`
    (the org's UUID) and `name` stay: neither is in the JWT at all."""

    id: str
    name: str


class LoginRoleOut(BaseModel):
    """Like app.api.v1.users.responses.RoleOut, minus `name` — the role's
    display name is already the JWT access token's own `role` claim. `id`
    (the role's UUID) stays: it's not in the JWT at all."""

    id: str


class LoginUserOut(BaseModel):
    id: uuid.UUID
    name: str | None
    email: str
    # The real `username` column when set, else derived from the email's
    # local part — see app.modules.users.service.display_username.
    username: str
    tenant: LoginTenantOut | None
    role: LoginRoleOut | None
    department: Any | None
    clearance_level: Any | None
    permissions: list[str]
    attributes: dict[str, Any]


class LinksOut(BaseModel):
    profile: str
    refresh: str
    logout: str


class TokenResponse(BaseModel):
    # access_token/refresh_token both None together means an MFA challenge
    # is in progress (see mfa_required/mfa_challenge_token) rather than a
    # completed login.
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None
    mfa_required: bool = False
    mfa_challenge_token: str | None = None
    message: str | None = None
    user: LoginUserOut | None = None
    session: SessionOut | None = None
    links: LinksOut | None = None


class GoogleAuthorizeResponse(BaseModel):
    authorization_url: str


class ForgotPasswordResponse(BaseModel):
    message: str = "If that email is registered, a password reset link has been sent."
    # Only populated when settings.debug is True — there's no email/notification
    # service in this stack, so dev/test environments get the token directly.
    reset_token: str | None = None


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class MfaConfirmResponse(BaseModel):
    # Shown once — only sha256 hashes are persisted server-side.
    recovery_codes: list[str]


class VerifyEmailResponse(BaseModel):
    status: str = "VERIFIED"
    verified_at: datetime
    message: str = "Email verified successfully"


class AcceptInviteResponse(BaseModel):
    user_id: uuid.UUID
    tenant_id: str
    role: str
    status: str


class SwitchTenantResponse(BaseModel):
    """``tenant_id``/``role`` were dropped — both are already on the
    re-minted ``access_token``'s own claims (see AuthService.switch_tenant),
    so the caller decodes the token rather than reading the same values
    twice."""

    access_token: str
