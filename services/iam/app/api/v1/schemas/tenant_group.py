"""Request/response models for the Tenant entity and its many-to-many link
to Organization.

Named "tenant group" in the API to stay distinct from this codebase's
pre-existing "tenant" vocabulary (Organization.slug, the `tenant_id` claim
on access tokens, /login, /users/me, /switch-tenant, and the
POST /api/v1/tenants organization-bootstrap endpoint) — see
app.services.tenant_service for the full rationale.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TenantGroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")


class TenantGroupUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


class TenantGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LinkOrganizationRequest(BaseModel):
    organization_id: uuid.UUID


class TenantGroupOrganizationOut(BaseModel):
    """A summary of an Organization linked to a tenant group — not the full
    OrganizationOut, this endpoint has no need for owner_id/default_attributes."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
