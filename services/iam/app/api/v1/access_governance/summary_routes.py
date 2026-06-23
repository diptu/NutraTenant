"""GET /api/v1/access/{user_id} (User and Access APIs Specification) — a
read-only summary of a user's effective roles/permissions/attributes,
combining the global (platform-wide) role assignments with their current
tenant's org-membership role/permissions and merged ABAC attribute bag."""

from __future__ import annotations

import uuid

from app.api.v1.access_governance.summary_responses import AccessSummaryOut
from app.api.v1.dependencies import get_current_user, get_user_service
from app.domain.exceptions import ForbiddenError
from app.modules.roles.dependencies import get_role_service
from app.modules.roles.service import RoleService
from app.modules.users.models import User
from app.modules.users.service import UserService
from fastapi import APIRouter, Depends, Query

router = APIRouter(prefix="/access", tags=["access"])


@router.get("/{user_id}", response_model=AccessSummaryOut)
async def get_user_access(
    user_id: uuid.UUID,
    tenant_id: str | None = Query(
        default=None,
        description="Organization slug to resolve the tenant-scoped role/permissions "
        "for, when the user belongs to more than one. Defaults to their sole "
        "organization when they have exactly one.",
    ),
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
    role_service: RoleService = Depends(get_role_service),
) -> AccessSummaryOut:
    if not current_user.is_superuser and current_user.id != user_id:
        raise ForbiddenError("You can only view your own access summary")

    user = await user_service.get_by_id(user_id)
    context = await user_service.get_profile_context_for_user(user_id, tenant_id)
    global_assignments = await role_service.list_user_roles(user_id)

    roles = {a.role.code for a in global_assignments}
    if context.role is not None:
        roles.add(context.role.code)

    return AccessSummaryOut(
        user_id=user.id,
        roles=sorted(roles),
        permissions=context.permissions,
        effective_attributes=user.attributes,
    )
