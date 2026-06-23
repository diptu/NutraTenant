"""Response models for organization lifecycle/membership management and the
root tenant-bootstrap API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    owner_id: uuid.UUID
    is_active: bool
    is_reserved: bool
    default_attributes: dict[str, Any]


class OrganizationMemberOut(BaseModel):
    user_id: uuid.UUID
    role_code: str
    is_active: bool


class InvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    role_code: str
    expires_at: datetime
    # Only populated when settings.debug is True — there's no email/
    # notification service in this stack, so dev/test environments get the
    # token directly instead of via a delivered email.
    invitation_token: str | None = None


class CreateInviteResponse(BaseModel):
    invite_token: str
    expires_in: int
    tenant_id: str


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
