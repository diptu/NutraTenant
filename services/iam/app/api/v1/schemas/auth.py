"""Request/response models for the auth + Google federation endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.api.v1.schemas.user import UserOut

__all__ = [
    "ChangePasswordRequest",
    "ForgotPasswordRequest",
    "ForgotPasswordResponse",
    "GoogleAuthorizeResponse",
    "LinksOut",
    "LoginRequest",
    "LoginUserOut",
    "MfaConfirmRequest",
    "MfaConfirmResponse",
    "MfaDisableRequest",
    "MfaLoginVerifyRequest",
    "MfaSetupResponse",
    "RefreshRequest",
    "RegisterRequest",
    "ResetPasswordRequest",
    "RoleOut",
    "SessionOut",
    "TenantOut",
    "TokenResponse",
    "UserOut",
]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=150)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    # Disambiguates which organization to bind the session to when the
    # account belongs to more than one — see AuthService._resolve_tenant.
    # Omit it when the account has zero or one organization.
    tenant_id: uuid.UUID | None = None


class RefreshRequest(BaseModel):
    # The httponly cookie set by /login is the primary transport; this body
    # field exists for non-browser clients (mobile/native, service-to-
    # service) that received the refresh token in the login response body
    # instead and have nowhere to keep a cookie.
    refresh_token: str | None = None


class TenantOut(BaseModel):
    id: str
    tenant_id: str
    name: str


class RoleOut(BaseModel):
    id: str
    name: str


class SessionOut(BaseModel):
    session_id: str
    issued_at: datetime
    expires_at: datetime
    ip_address: str | None
    device: str
    last_login: datetime | None


class LoginUserOut(BaseModel):
    id: uuid.UUID
    name: str | None
    email: str
    # Derived from the email's local part — there is no separate `username`
    # column on `User`, this just satisfies clients that expect the field.
    username: str
    tenant: TenantOut | None
    role: RoleOut | None
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


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: str = "If that email is registered, a password reset link has been sent."
    # Only populated when settings.debug is True — there's no email/notification
    # service in this stack, so dev/test environments get the token directly.
    reset_token: str | None = None


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class MfaConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class MfaConfirmResponse(BaseModel):
    # Shown once — only sha256 hashes are persisted server-side.
    recovery_codes: list[str]


class MfaDisableRequest(BaseModel):
    current_password: str
    code: str = Field(min_length=6, max_length=32)


class MfaLoginVerifyRequest(BaseModel):
    mfa_challenge_token: str
    code: str = Field(min_length=6, max_length=32)
