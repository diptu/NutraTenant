"""Cache-aside resolution of a member's effective permission codes.

Deliberately duck-typed on `member.user_id` / `member.role.id` /
`member.role.updated_at` / `member.role.permissions[*].code` rather than
importing UserOrganizationRole directly — any object with that shape works
(including plain test doubles), as long as `role.role_permissions` /
`.permission` were already eager-loaded by the caller.

The cache key embeds `role.updated_at`, so a role's permission set changing
(which bumps `updated_at` — see RoleService.add_permission/remove_permission)
naturally busts stale cache entries without any explicit invalidation call.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.cache import PermissionCache, get_permission_cache


async def get_member_permissions(
    organization_id: uuid.UUID, member: Any, *, cache: PermissionCache | None = None
) -> set[str]:
    """`cache` is injectable (OrganizationService passes its own, DI'd
    instance so tests can override it) but optional — falls back to the
    module-level singleton for direct/standalone callers."""
    cache = cache or get_permission_cache()
    cache_key = (
        f"member-permissions:{organization_id}:{member.user_id}:"
        f"{member.role.id}:{member.role.updated_at.isoformat()}"
    )

    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    computed = {p.code for p in member.role.permissions}
    await cache.set(cache_key, computed, ttl_seconds=300)
    return computed
