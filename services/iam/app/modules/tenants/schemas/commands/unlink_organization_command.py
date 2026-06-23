from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UnlinkOrganizationCommand:
    tenant_id: uuid.UUID
    organization_id: uuid.UUID
