from __future__ import annotations

import uuid

from app.modules.groups.exceptions import GroupNotFoundError, InvalidGroupHierarchyError
from app.modules.groups.repositories.interfaces.group_repository import GroupRepository


async def validate_parent(
    groups: GroupRepository,
    parent_group_id: uuid.UUID,
    organization_id: uuid.UUID,
    *,
    group_id: uuid.UUID | None = None,
) -> None:
    if parent_group_id == group_id:
        raise InvalidGroupHierarchyError("A group cannot be its own parent")

    parent = await groups.get_by_id(parent_group_id)
    if parent is None:
        raise GroupNotFoundError(f"No group with id '{parent_group_id}'")
    if parent.organization_id != organization_id:
        raise InvalidGroupHierarchyError("parent_group_id must belong to the same tenant")

    if group_id is not None:
        ancestors = await groups.list_ancestor_ids(parent_group_id)
        if group_id in ancestors:
            raise InvalidGroupHierarchyError(
                "parent_group_id would create a cycle in the group hierarchy"
            )
