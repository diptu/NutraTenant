from __future__ import annotations

import uuid

from app.modules.groups.exceptions import GroupNotFoundError
from app.modules.groups.models import Group
from app.modules.groups.repositories.interfaces.group_repository import GroupRepository


async def get_group(groups: GroupRepository, group_id: uuid.UUID) -> Group:
    group = await groups.get_by_id(group_id)
    if group is None:
        raise GroupNotFoundError(f"No group with id '{group_id}'")
    return group


async def get_group_in_org(groups: GroupRepository, group_id: uuid.UUID, organization_id: uuid.UUID) -> Group:
    """Same as :func:`get_group`, but also enforces tenant scope — used by
    the membership flows so a caller can't reference a group from a
    different tenant by id, and so the 404 leaks no signal either way."""
    group = await get_group(groups, group_id)
    if group.organization_id != organization_id:
        raise GroupNotFoundError(f"No group with id '{group_id}'")
    return group
