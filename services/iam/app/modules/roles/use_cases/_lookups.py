from __future__ import annotations

import uuid

from app.modules.roles.exceptions import RoleNotFoundError
from app.modules.roles.models import Role
from app.modules.roles.repositories.interfaces.role_repository import RoleRepository


async def get_any_role(roles: RoleRepository, role_id: uuid.UUID) -> Role:
    """Global *or* org-scoped — used by lookups/mutations that work on either."""
    role = await roles.get_by_id(role_id)
    if role is None:
        raise RoleNotFoundError(f"No role with id '{role_id}'")
    return role


async def get_global_role(roles: RoleRepository, role_id: uuid.UUID) -> Role:
    """Global (organization_id IS NULL) roles only."""
    role = await roles.get_by_id(role_id)
    if role is None or role.organization_id is not None:
        raise RoleNotFoundError(f"No global role with id '{role_id}'")
    return role


async def reload_with_permissions(roles: RoleRepository, role_id: uuid.UUID) -> Role:
    reloaded = await roles.get_with_permissions(role_id)
    assert reloaded is not None
    return reloaded
