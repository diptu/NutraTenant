"""Request bodies for the Tenant entity and its many-to-many link to
Organization.

Exposed at the /tenant-groups URL prefix to stay distinct from this
codebase's pre-existing "tenant" vocabulary (Organization.slug, the
`tenant_id` claim on access tokens, /login, /users/me, /switch-tenant, and
the POST /api/v1/tenants organization-bootstrap endpoint) — see
app.modules.tenants.service for the full rationale.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class TenantGroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")


class TenantGroupUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


class LinkOrganizationRequest(BaseModel):
    organization_id: uuid.UUID
