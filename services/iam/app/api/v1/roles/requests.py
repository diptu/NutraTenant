"""Request bodies for role management — both the global (platform-wide)
catalog and tenant-scoped custom roles (Role_API_Specification_Extended.md).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class RoleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$")
    description: str | None = Field(default=None, max_length=500)
    priority: int = 0
    # Permission codes to grant immediately at creation time.
    permissions: list[str] = Field(default_factory=list)
    # Escape hatch, superuser-only: explicitly target a tenant other than
    # the caller's own session context (e.g. platform-ops bootstrapping a
    # role for a tenant the superuser isn't a member of — see scripts/seed.sh).
    # Omit it to use the caller's current tenant (or, for a superuser with
    # no tenant context, a global role).
    tenant_id: str | None = None


class RoleUpdateRequest(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    priority: int | None = None
    is_active: bool | None = None


class AssignRolePermissionsRequest(BaseModel):
    permissions: list[str] = Field(min_length=1)


class RemoveRolePermissionsRequest(BaseModel):
    permissions: list[str] = Field(min_length=1)


class AssignUsersToRoleRequest(BaseModel):
    user_ids: list[uuid.UUID] = Field(min_length=1)


class CloneRoleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$")


# -- the pre-existing, unchanged global (platform-wide) role-assignment
# contract (POST/DELETE /roles/{role_id}/assignments, GET /roles/assignments/{user_id})
# — distinct from AssignUsersToRoleRequest above, which is the new spec's
# tenant-scoped org-membership mechanism.


class AssignRoleRequest(BaseModel):
    user_id: uuid.UUID
