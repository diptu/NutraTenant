"""Request bodies for the reserved tenant_id blocklist
(/api/v1/reserved-tenant-ids)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReservedTenantIdCreateRequest(BaseModel):
    tenant_id: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    reason: str | None = Field(default=None, max_length=255)
