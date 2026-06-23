"""Response models for the Tenant entity and its many-to-many link to
Organization."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TenantGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TenantGroupOrganizationOut(BaseModel):
    """A summary of an Organization linked to a tenant group — not the full
    OrganizationOut, this endpoint has no need for owner_id/default_attributes."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
