from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RevokeInvitationCommand:
    organization_id: uuid.UUID
    invitation_id: uuid.UUID
