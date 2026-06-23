"""Response models for the reserved tenant_id blocklist
(/api/v1/reserved-tenant-ids)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReservedTenantIdOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: str
    reason: str | None
    created_by: uuid.UUID | None
    created_at: datetime
