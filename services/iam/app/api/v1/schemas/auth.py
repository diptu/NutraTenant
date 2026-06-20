"""Request/response models for the auth + Google federation endpoints."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.api.v1.schemas.user import UserOut

__all__ = [
    "ChangePasswordRequest",
    "ForgotPasswordRequest",
    "ForgotPasswordResponse",
    "GoogleAuthorizeResponse",
    "LoginRequest",
    "RegisterRequest",
    "ResetPasswordRequest",
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


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


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
