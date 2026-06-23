from __future__ import annotations

import uuid

from app.core.cache import PermissionCache
from app.modules.organizations.org_permissions import get_member_permissions
from app.modules.organizations.repositories.interfaces.organization_repository import (
    OrganizationRepository,
)
from app.modules.roles.models import Role
from app.modules.roles.repositories.interfaces.role_repository import RoleRepository
from app.shared.exceptions.base import ForbiddenError


async def ensure_can_grant_role(
    orgs: OrganizationRepository,
    roles: RoleRepository,
    organization_id: uuid.UUID,
    *,
    granter_id: uuid.UUID,
    target_role: Role,
    permission_cache: PermissionCache | None,
) -> None:
    """The privilege-escalation guard: granting a role whose permissions
    exceed what the granter themself holds is refused. Reachable today
    via PATCH .../members/{user_id} (open to any member, not just the
    owner) — add_member itself stays owner-or-superuser-gated at the
    route, where this is a defense-in-depth safety net instead.
    """
    granter_membership = await orgs.get_membership(organization_id, granter_id)
    if granter_membership is None:
        return  # superuser acting without being a member — already vetted by the route
    if granter_membership.role.code == "owner":
        return

    # "owner" carries no permission *codes* of its own — it's a
    # structural distinction, not a grantable permission set — so the
    # subset check below can't see it. A non-owner must never be able
    # to grant ownership, full stop, regardless of what permissions
    # they hold.
    if target_role.code == "owner":
        raise ForbiddenError("Only the organization owner can grant ownership")

    target_role_with_permissions = await roles.get_with_permissions(target_role.id)
    target_codes = {
        p.code for p in (target_role_with_permissions.permissions if target_role_with_permissions else [])
    }
    if not target_codes:
        return

    granter_codes = await get_member_permissions(
        organization_id, granter_membership, cache=permission_cache
    )
    if not target_codes.issubset(granter_codes):
        raise ForbiddenError("Cannot grant a role with permissions exceeding your own")
