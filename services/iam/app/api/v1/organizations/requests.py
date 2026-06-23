"""Request bodies for organization lifecycle/membership management and the
root tenant-bootstrap API.

CreateInviteRequest/CreateTenantRequest back a second contract for the same
underlying OrganizationService flows (invite_member / AuthService.create_tenant)
under the /tenants URL prefix — for a client that expects `role`/`tenant_id`
field names instead of `role_code`/`organization_id`.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, EmailStr, Field


class OrganizationCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    description: str | None = Field(default=None, max_length=500)


class OrganizationUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    default_attributes: dict[str, Any] | None = None
    # Superuser-only, regardless of who's otherwise allowed to PATCH this
    # organization — see the extra gate in app.api.v1.organizations.routes.
    is_reserved: bool | None = None


class AddMemberRequest(BaseModel):
    user_id: uuid.UUID
    role_code: str = Field(default="member", max_length=100)


class UpdateMemberRoleRequest(BaseModel):
    role_code: str = Field(min_length=1, max_length=100)


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role_code: str = Field(default="member", max_length=100)


class AcceptInvitationRequest(BaseModel):
    token: str


class CreateInviteRequest(BaseModel):
    email: EmailStr
    role: str = Field(min_length=1, max_length=100)


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
