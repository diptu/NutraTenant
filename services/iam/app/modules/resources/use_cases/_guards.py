from __future__ import annotations

import uuid

from app.modules.resources.models import Resource
from app.shared.exceptions.base import ForbiddenError


def require_owner_or_superuser(
    resource: Resource, requester_id: uuid.UUID, is_superuser: bool
) -> None:
    if is_superuser or resource.created_by == requester_id:
        return
    raise ForbiddenError("Only the resource's creator or an admin can modify it")
