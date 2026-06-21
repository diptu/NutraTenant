"""Role lookup/provisioning helpers shared by AuthService and OrganizationService.

`resolve_role_in_org` resolves a free-form role string (a display name typed
into an admin form, e.g. "Member"/"Admin") to an org-scoped Role — used by
the tenant-invite and admin-provisioning endpoints, which accept `role`
rather than the `role_code` every other endpoint in this service takes
directly. `provision_role` is the idempotent get-or-create used to seed an
org's standard role set at creation time.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.infrastructure.db.models.role import Role
from app.infrastructure.db.repositories.role_repo import RoleRepository
from sqlalchemy.ext.asyncio import AsyncSession

# The (code, display name) pairs every organization is auto-provisioned with
# at creation, regardless of which endpoint creates it (self-service
# POST /organizations or the POST /tenants bootstrap API). `owner` is the
# one structural role — see the module docstring on OrganizationService.
DEFAULT_ORG_ROLES: tuple[tuple[str, str], ...] = (
    ("owner", "Owner"),
    ("admin", "Admin"),
    ("member", "Member"),
    ("viewer", "Viewer"),
)


async def resolve_role_in_org(roles: RoleRepository, organization_id: uuid.UUID, role: str) -> Role | None:
    """Tries an exact `code` match first (lower-cased — codes are
    conventionally lower_snake_case, e.g. "member"), then falls back to an
    exact `name` match (e.g. "Member") for custom roles whose code differs
    from their display name."""
    by_code = await roles.get_by_code_in_org(organization_id, role.strip().lower())
    if by_code is not None:
        return by_code
    return await roles.get_by_name_in_org(organization_id, role.strip())


async def provision_role(
    session: AsyncSession,
    roles: RoleRepository,
    organization_id: uuid.UUID,
    *,
    code: str,
    name: str,
) -> Role:
    """Idempotent: returns the existing role if this org already has one
    with this code, otherwise creates it. Flushes (not commits) — the
    caller owns the transaction boundary."""
    existing = await roles.get_by_code_in_org(organization_id, code)
    if existing is not None:
        return existing
    now = datetime.now(UTC)
    role = Role(
        id=uuid.uuid4(),
        name=name,
        code=code,
        organization_id=organization_id,
        is_system=True,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    roles.add(role)
    await session.flush()
    return role
