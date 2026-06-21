"""Request/response models for tenant-scoped invitation creation and the
root tenant-bootstrap API.

Distinct from app.api.v1.schemas.organization's InviteMemberRequest/
InvitationOut — this is a second contract for the same underlying
OrganizationService.invite_member, for a client that expects `role` (a
display name, resolved via app.services.role_lookup) and `tenant_id`/
`invite_token`/`expires_in` field names instead of `role_code`/
`organization_id`/`invitation_token`/`expires_at`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field


class CreateInviteRequest(BaseModel):
    email: EmailStr
    role: str = Field(min_length=1, max_length=100)


class CreateInviteResponse(BaseModel):
    invite_token: str
    expires_in: int
    tenant_id: str


class PasswordPolicy(BaseModel):
    min_length: int = Field(default=8, ge=1, le=256)
    require_uppercase: bool = False
    require_number: bool = False
    require_symbol: bool = False


class TenantSettingsIn(BaseModel):
    allow_self_signup: bool = False
    mfa_required: bool = False
    session_timeout_minutes: int = Field(default=60, ge=1)
    password_policy: PasswordPolicy = Field(default_factory=PasswordPolicy)


class CreateTenantRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    # The org's slug — underscore-friendly (the spec's own examples use
    # "apple_corp"), looser than OrganizationCreateRequest's hyphen-only
    # pattern since there's no DB-level character-set constraint to match.
    tenant_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9]+([_-][a-z0-9]+)*$")
    owner_email: EmailStr
    plan: str = Field(default="free", max_length=50)
    settings: TenantSettingsIn = Field(default_factory=TenantSettingsIn)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TenantDetailOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    status: str
    plan: str
    created_at: datetime
    settings: dict[str, Any]
    metadata: dict[str, Any]


class TenantBootstrapOwnerOut(BaseModel):
    user_id: str
    email: str
    role: str
    status: str


class TenantBootstrapInfo(BaseModel):
    invite_token: str
    invite_expiry: int
    next_step: str


class CreateTenantResponse(BaseModel):
    tenant: TenantDetailOut
    owner: TenantBootstrapOwnerOut
    default_roles: list[str]
    # None when the owner already had an account — nothing to redeem.
    bootstrap: TenantBootstrapInfo | None = None
    message: str
