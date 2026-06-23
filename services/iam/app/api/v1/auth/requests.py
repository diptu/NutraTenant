"""Request bodies for the auth + Google federation endpoints."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

__all__ = [
    "AcceptInviteRequest",
    "ChangePasswordRequest",
    "ForgotPasswordRequest",
    "LoginClientMetadata",
    "LoginContextMetadata",
    "LoginRequest",
    "MfaConfirmRequest",
    "MfaDisableRequest",
    "MfaLoginVerifyRequest",
    "RefreshRequest",
    "RegisterRequest",
    "ResetPasswordRequest",
    "SwitchTenantRequest",
    "VerifyEmailRequest",
]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=150)


class LoginClientMetadata(BaseModel):
    """Client-reported device info — optional, every field optional. When
    given, it takes precedence over the User-Agent header for the login
    response's `session.device` description (see app.api.v1.auth.routes.login);
    never used for any security decision."""

    device_id: str | None = None
    device_name: str | None = None
    platform: str | None = None
    browser: str | None = None


class LoginContextMetadata(BaseModel):
    """Client-reported request context — optional, every field optional, and
    purely informational today (not yet persisted or used by any login
    decision). `ip_address` here is never trusted over the actual connection
    address (see AuthService.login's own `ip_address` parameter) — accepting
    a client-supplied value as authoritative would be a spoofing risk."""

    ip_address: str | None = None
    timezone: str | None = None
    locale: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    # The organization's *slug* (e.g. "apple_corp"), not its id — disambiguates
    # which organization to bind the session to when the account belongs to
    # more than one. See AuthService._resolve_tenant. Omit it when the
    # account has zero or one organization.
    tenant_id: str | None = None
    client: LoginClientMetadata | None = None
    context: LoginContextMetadata | None = None


class RefreshRequest(BaseModel):
    # The httponly cookie set by /login is the primary transport; this body
    # field exists for non-browser clients (mobile/native, service-to-
    # service) that received the refresh token in the login response body
    # instead and have nowhere to keep a cookie.
    refresh_token: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class MfaConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class MfaDisableRequest(BaseModel):
    current_password: str
    code: str = Field(min_length=6, max_length=32)


class MfaLoginVerifyRequest(BaseModel):
    mfa_challenge_token: str
    code: str = Field(min_length=6, max_length=32)


class VerifyEmailRequest(BaseModel):
    verification_token: str


class AcceptInviteRequest(BaseModel):
    invite_token: str
    name: str | None = Field(default=None, max_length=150)
    password: str = Field(min_length=8, max_length=128)


class SwitchTenantRequest(BaseModel):
    tenant_id: str
