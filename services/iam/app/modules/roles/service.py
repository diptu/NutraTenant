"""Coarse-grained, platform-wide (non-org-scoped) role management, plus the
role lookup/provisioning helpers shared by AuthService and OrganizationService.

Distinct from app.modules.organizations.service's tenant-scoped owner/member
roles — these are global roles (Admin/Member/Guest, ...) assigned directly
to a user via the ``user_roles`` table, used by the fast-path RBAC guard
(app.api.v1.dependencies.require_global_role) before any ABAC evaluation
even runs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.organizations.repositories.sqlalchemy.organization_repository import (
    OrganizationRepository,
)
from app.modules.permissions.repositories.sqlalchemy.permission_repository import (
    PermissionRepository,
)
from app.modules.roles.exceptions import RoleNotFoundError
from app.modules.roles.models import Role, UserRole
from app.modules.roles.repositories.interfaces.role_repository import (
    RoleRepository as RoleRepositoryProtocol,
)
from app.modules.roles.repositories.sqlalchemy.role_repository import (
    RoleRepository,
    UserRoleRepository,
)
from app.modules.roles.schemas.commands.add_role_permissions_command import (
    AddRolePermissionsCommand,
)
from app.modules.roles.schemas.commands.assign_role_command import AssignRoleCommand
from app.modules.roles.schemas.commands.bulk_assign_role_users_command import (
    BulkAssignRoleUsersCommand,
)
from app.modules.roles.schemas.commands.clone_role_command import CloneRoleCommand
from app.modules.roles.schemas.commands.create_role_command import CreateRoleCommand
from app.modules.roles.schemas.commands.delete_role_command import DeleteRoleCommand
from app.modules.roles.schemas.commands.remove_role_permission_command import (
    RemoveRolePermissionCommand,
)
from app.modules.roles.schemas.commands.remove_role_permissions_by_code_command import (
    RemoveRolePermissionsByCodeCommand,
)
from app.modules.roles.schemas.commands.revoke_role_command import RevokeRoleCommand
from app.modules.roles.schemas.commands.update_role_command import UpdateRoleCommand
from app.modules.roles.use_cases._lookups import get_any_role, get_global_role
from app.modules.roles.use_cases.add_role_permissions import AddRolePermissionsUseCase
from app.modules.roles.use_cases.assign_role import AssignRoleUseCase
from app.modules.roles.use_cases.bulk_assign_role_users import BulkAssignRoleUsersUseCase
from app.modules.roles.use_cases.clone_role import CloneRoleUseCase
from app.modules.roles.use_cases.create_role import CreateRoleUseCase
from app.modules.roles.use_cases.delete_role import DeleteRoleUseCase
from app.modules.roles.use_cases.remove_role_permission import RemoveRolePermissionUseCase
from app.modules.roles.use_cases.remove_role_permissions_by_code import (
    RemoveRolePermissionsByCodeUseCase,
)
from app.modules.roles.use_cases.revoke_role import RevokeRoleUseCase
from app.modules.roles.use_cases.seed_default_roles import (
    DEFAULT_GLOBAL_ROLES,
    SeedDefaultRolesUseCase,
)
from app.modules.roles.use_cases.update_role import UpdateRoleUseCase
from app.modules.users.models import User
from app.modules.users.repositories.sqlalchemy.user_repository import UserRepository

__all__ = [
    "DEFAULT_GLOBAL_ROLES",
    "DEFAULT_ORG_ROLES",
    "RoleService",
    "provision_role",
    "resolve_role_in_org",
]

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


async def resolve_role_in_org(
    roles: RoleRepositoryProtocol, organization_id: uuid.UUID, role: str
) -> Role | None:
    """Tries an exact `code` match first (lower-cased — codes are
    conventionally lower_snake_case, e.g. "member"), then falls back to an
    exact `name` match (e.g. "Member") for custom roles whose code differs
    from their display name."""
    by_code = await roles.get_by_code_in_org(organization_id, role.strip().lower())
    if by_code is not None:
        return by_code
    return await roles.get_by_name_in_org(organization_id, role.strip())


async def provision_role(
    session,
    roles: RoleRepositoryProtocol,
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


class RoleService:
    def __init__(self, session) -> None:
        self._session = session
        self._roles = RoleRepository(session)
        self._user_roles = UserRoleRepository(session)
        self._users = UserRepository(session)
        self._permissions = PermissionRepository(session)
        self._audit_log = AuditLogRepository(session)
        self._orgs = OrganizationRepository(session)
        self._seed_use_case = SeedDefaultRolesUseCase(session, self._roles)
        self._create_use_case = CreateRoleUseCase(session, self._roles, self._permissions)
        self._update_use_case = UpdateRoleUseCase(session, self._roles)
        self._clone_use_case = CloneRoleUseCase(self._roles, self._create_use_case)
        self._delete_use_case = DeleteRoleUseCase(session, self._roles)
        self._add_permissions_use_case = AddRolePermissionsUseCase(
            session, self._roles, self._permissions
        )
        self._remove_permission_use_case = RemoveRolePermissionUseCase(
            session, self._roles, self._permissions
        )
        self._remove_permissions_by_code_use_case = RemoveRolePermissionsByCodeUseCase(
            session, self._roles, self._permissions
        )
        self._bulk_assign_users_use_case = BulkAssignRoleUsersUseCase(
            session, self._roles, self._orgs, self._audit_log
        )
        self._assign_role_use_case = AssignRoleUseCase(
            session, self._roles, self._user_roles, self._users, self._audit_log
        )
        self._revoke_role_use_case = RevokeRoleUseCase(
            session, self._roles, self._user_roles, self._audit_log
        )

    # -- catalog -----------------------------------------------------------

    async def seed_defaults(self) -> list[Role]:
        return await self._seed_use_case.execute()

    async def list_roles(self) -> list[Role]:
        return await self._roles.list_all_global()

    async def get_role(self, role_id: uuid.UUID) -> Role:
        """Global (organization_id IS NULL) roles only — used by the
        platform-wide role catalog endpoints."""
        return await get_global_role(self._roles, role_id)

    async def get_any_role(self, role_id: uuid.UUID) -> Role:
        """Global *or* org-scoped — used by lookups/mutations that work on
        either (permission assignment, generic by-id retrieval)."""
        return await get_any_role(self._roles, role_id)

    async def get_role_with_permissions(self, role_id: uuid.UUID) -> Role:
        """Same lookup as get_any_role, but with role.permissions safe to
        access (eager-loaded) — used by GET /roles/{role_id}/permissions."""
        role = await self._roles.get_with_permissions(role_id)
        if role is None:
            raise RoleNotFoundError(f"No role with id '{role_id}'")
        return role

    async def get_by_code(self, code: str) -> Role:
        """Global (organization_id IS NULL) role lookup by code — used by
        POST /users/{user_id}/roles, which (unlike POST /roles/{role_id}/assignments)
        takes a free-form role code rather than a role_id. Codes are
        conventionally lower_snake_case, so the lookup is case-insensitive."""
        role = await self._roles.get_by_code(code.strip().lower())
        if role is None:
            raise RoleNotFoundError(f"No global role with code '{code}'")
        return role

    async def create_role(
        self,
        *,
        name: str,
        code: str,
        description: str | None,
        organization_id: uuid.UUID | None = None,
        priority: int = 0,
        permission_codes: list[str] | None = None,
        created_by: uuid.UUID | None = None,
    ) -> Role:
        command = CreateRoleCommand(
            name=name,
            code=code,
            description=description,
            organization_id=organization_id,
            priority=priority,
            permission_codes=permission_codes,
            created_by=created_by,
        )
        return await self._create_use_case.execute(command)

    async def update_role(
        self,
        role_id: uuid.UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        priority: int | None = None,
        is_active: bool | None = None,
        updated_by: uuid.UUID | None = None,
    ) -> Role:
        command = UpdateRoleCommand(
            role_id=role_id,
            name=name,
            description=description,
            priority=priority,
            is_active=is_active,
            updated_by=updated_by,
        )
        return await self._update_use_case.execute(command)

    async def set_active(self, role_id: uuid.UUID, is_active: bool, *, updated_by: uuid.UUID | None) -> Role:
        """PATCH .../activate|.../deactivate — same system-role guard as
        update_role, just without requiring the caller to also resend
        name/description/priority."""
        return await self.update_role(role_id, is_active=is_active, updated_by=updated_by)

    async def clone_role(
        self,
        role_id: uuid.UUID,
        *,
        name: str,
        code: str,
        created_by: uuid.UUID | None,
    ) -> Role:
        command = CloneRoleCommand(role_id=role_id, name=name, code=code, created_by=created_by)
        return await self._clone_use_case.execute(command)

    async def delete_role(self, role_id: uuid.UUID) -> None:
        await self._delete_use_case.execute(DeleteRoleCommand(role_id=role_id))

    # -- permission assignment (the role's own grants, not a user's) -------

    async def add_permissions(self, role_id: uuid.UUID, codes: list[str], *, assigned_by: uuid.UUID) -> Role:
        command = AddRolePermissionsCommand(role_id=role_id, codes=codes, assigned_by=assigned_by)
        return await self._add_permissions_use_case.execute(command)

    async def remove_permission(self, role_id: uuid.UUID, permission_id: uuid.UUID) -> Role:
        command = RemoveRolePermissionCommand(role_id=role_id, permission_id=permission_id)
        return await self._remove_permission_use_case.execute(command)

    async def remove_permissions_by_code(self, role_id: uuid.UUID, codes: list[str]) -> Role:
        command = RemoveRolePermissionsByCodeCommand(role_id=role_id, codes=codes)
        return await self._remove_permissions_by_code_use_case.execute(command)

    async def count_permissions(self, role_id: uuid.UUID) -> int:
        return await self._roles.count_permissions(role_id)

    # -- users holding this role (this role's side, not the global table) ---

    async def count_users(self, role: Role) -> int:
        return await self._roles.count_users(role)

    async def list_role_users(self, role_id: uuid.UUID) -> list[User]:
        role = await self.get_any_role(role_id)
        return await self._roles.list_users(role)

    async def bulk_assign_users(
        self, role_id: uuid.UUID, user_ids: list[uuid.UUID], *, actor_id: uuid.UUID
    ) -> int:
        command = BulkAssignRoleUsersCommand(role_id=role_id, user_ids=user_ids, actor_id=actor_id)
        return await self._bulk_assign_users_use_case.execute(command)

    # -- catalog listing (paginated) ------------------------------------------

    async def list_paginated(
        self,
        *,
        organization_id: uuid.UUID | None,
        page: int,
        page_size: int,
        search: str | None,
        is_system: bool | None,
        is_active: bool | None,
    ) -> tuple[list[Role], int]:
        offset = (page - 1) * page_size
        return await self._roles.search_catalog(
            organization_id=organization_id,
            search=search,
            is_system=is_system,
            is_active=is_active,
            limit=page_size,
            offset=offset,
        )

    # -- assignment ----------------------------------------------------------

    async def assign_role(
        self, *, user_id: uuid.UUID, role_id: uuid.UUID, assigned_by: uuid.UUID | None
    ) -> UserRole:
        command = AssignRoleCommand(user_id=user_id, role_id=role_id, assigned_by=assigned_by)
        return await self._assign_role_use_case.execute(command)

    async def revoke_role(self, *, user_id: uuid.UUID, role_id: uuid.UUID) -> None:
        command = RevokeRoleCommand(user_id=user_id, role_id=role_id)
        await self._revoke_role_use_case.execute(command)

    async def list_user_roles(self, user_id: uuid.UUID) -> list[UserRole]:
        return await self._user_roles.list_for_user(user_id)

    async def has_role(self, user_id: uuid.UUID, code: str) -> bool:
        role = await self._roles.get_by_code(code)
        if role is None:
            return False
        return await self._user_roles.has_role(user_id, role.id)
