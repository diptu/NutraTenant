"""The platform permission catalog — framework-free constants.

Seeded into the `permissions` table (and granted in full to the global
`admin` role) by `app.core.rbac_seed.seed_rbac_catalog`.
"""

from __future__ import annotations

PLATFORM_PERMISSIONS: dict[str, str] = {
    "USERS_READ": "users:read",
    "USERS_CREATE": "users:create",
    "USERS_UPDATE": "users:update",
    "USERS_DELETE": "users:delete",
    "ORGANIZATIONS_READ": "organizations:read",
    "ORGANIZATIONS_UPDATE": "organizations:update",
    "ORGANIZATIONS_DELETE": "organizations:delete",
    "RESOURCES_READ": "resources:read",
    "RESOURCES_MANAGE": "resources:manage",
    "ROLES_MANAGE": "roles:manage",
    "POLICIES_MANAGE": "policies:manage",
}
