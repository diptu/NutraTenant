"""Permission catalog CRUD, bulk/seed creation, role assignment, and usage/audit
lookups — backs the Permission Management API (POST/GET/PUT/DELETE /permissions,
.../bulk, .../seed, .../search, .../{id}/roles, .../{id}/usage, .../{id}/enable|disable,
.../{id}/audit).

Distinct from app.modules.roles.service's permission *grants on a role* (add_permissions/
remove_permission there mutate a Role; this service mutates the Permission catalog
itself and its role associations from the other side).
"""

from __future__ import annotations

import uuid

from app.audit import AuditLog, AuditLogRepository
from app.modules.permissions.exceptions import PermissionNotFoundError
from app.modules.permissions.models import Permission
from app.modules.permissions.repositories.sqlalchemy.permission_repository import (
    PermissionRepository,
)
from app.modules.permissions.schemas.commands.assign_permission_to_role_command import (
    AssignPermissionToRoleCommand,
)
from app.modules.permissions.schemas.commands.bulk_create_permissions_command import (
    BulkCreatePermissionsCommand,
)
from app.modules.permissions.schemas.commands.create_permission_command import (
    CreatePermissionCommand,
)
from app.modules.permissions.schemas.commands.delete_permission_command import (
    DeletePermissionCommand,
)
from app.modules.permissions.schemas.commands.remove_permission_from_role_command import (
    RemovePermissionFromRoleCommand,
)
from app.modules.permissions.schemas.commands.seed_resource_permissions_command import (
    SeedResourcePermissionsCommand,
)
from app.modules.permissions.schemas.commands.set_permission_status_command import (
    SetPermissionStatusCommand,
)
from app.modules.permissions.schemas.commands.update_permission_command import (
    UpdatePermissionCommand,
)
from app.modules.permissions.use_cases.assign_permission_to_role import (
    AssignPermissionToRoleUseCase,
)
from app.modules.permissions.use_cases.bulk_create_permissions import (
    BulkCreatePermissionsUseCase,
)
from app.modules.permissions.use_cases.create_permission import CreatePermissionUseCase
from app.modules.permissions.use_cases.delete_permission import DeletePermissionUseCase
from app.modules.permissions.use_cases.remove_permission_from_role import (
    RemovePermissionFromRoleUseCase,
)
from app.modules.permissions.use_cases.seed_resource_permissions import (
    SeedResourcePermissionsUseCase,
)
from app.modules.permissions.use_cases.set_permission_status import SetPermissionStatusUseCase
from app.modules.permissions.use_cases.update_permission import UpdatePermissionUseCase
from app.modules.permissions.value_objects import PermissionRiskLevel, PermissionStatus
from app.modules.policies.repositories.sqlalchemy.policy_repository import PolicyRepository
from app.modules.roles.models import Role
from app.modules.roles.repositories.sqlalchemy.role_repository import RoleRepository


class PermissionService:
    def __init__(self, session) -> None:
        self._session = session
        self._permissions = PermissionRepository(session)
        self._roles = RoleRepository(session)
        self._policies = PolicyRepository(session)
        self._audit_log = AuditLogRepository(session)
        self._create_use_case = CreatePermissionUseCase(session, self._permissions, self._audit_log)
        self._update_use_case = UpdatePermissionUseCase(session, self._permissions, self._audit_log)
        self._delete_use_case = DeletePermissionUseCase(session, self._permissions)
        self._bulk_create_use_case = BulkCreatePermissionsUseCase(
            session, self._permissions, self._audit_log
        )
        self._seed_use_case = SeedResourcePermissionsUseCase(
            session, self._permissions, self._audit_log
        )
        self._assign_to_role_use_case = AssignPermissionToRoleUseCase(
            session, self._permissions, self._roles, self._audit_log
        )
        self._remove_from_role_use_case = RemovePermissionFromRoleUseCase(
            session, self._permissions, self._audit_log
        )
        self._set_status_use_case = SetPermissionStatusUseCase(
            session, self._permissions, self._audit_log
        )

    # -- CRUD --------------------------------------------------------------

    async def create(
        self,
        *,
        resource: str,
        action: str,
        description: str | None,
        category: str | None,
        risk_level: PermissionRiskLevel,
        organization_id: uuid.UUID | None,
        created_by: uuid.UUID | None,
    ) -> Permission:
        command = CreatePermissionCommand(
            resource=resource,
            action=action,
            description=description,
            category=category,
            risk_level=risk_level,
            organization_id=organization_id,
            created_by=created_by,
        )
        return await self._create_use_case.execute(command)

    async def get(self, permission_id: uuid.UUID) -> Permission:
        permission = await self._permissions.get_by_id(permission_id)
        if permission is None:
            raise PermissionNotFoundError(f"No permission with id '{permission_id}'")
        return permission

    async def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        resource: str | None,
        action: str | None,
        category: str | None,
        status: str | None,
    ) -> tuple[list[Permission], int]:
        offset = (page - 1) * page_size
        return await self._permissions.search_catalog(
            resource=resource,
            action=action,
            category=category,
            status=status,
            limit=page_size,
            offset=offset,
        )

    async def search(self, q: str, *, limit: int = 50) -> list[Permission]:
        return await self._permissions.search(q, limit=limit)

    async def update(
        self,
        permission_id: uuid.UUID,
        *,
        description: str | None,
        category: str | None,
        risk_level: PermissionRiskLevel | None,
        updated_by: uuid.UUID | None,
    ) -> Permission:
        command = UpdatePermissionCommand(
            permission_id=permission_id,
            description=description,
            category=category,
            risk_level=risk_level,
            updated_by=updated_by,
        )
        return await self._update_use_case.execute(command)

    async def delete(self, permission_id: uuid.UUID) -> None:
        await self._delete_use_case.execute(DeletePermissionCommand(permission_id=permission_id))

    # -- bulk / seed ---------------------------------------------------------

    async def bulk_create(
        self,
        items: list[dict],
        *,
        organization_id: uuid.UUID | None,
        created_by: uuid.UUID | None,
    ) -> tuple[int, int]:
        command = BulkCreatePermissionsCommand(
            items=items, organization_id=organization_id, created_by=created_by
        )
        return await self._bulk_create_use_case.execute(command)

    async def seed_resources(self, resources: list[str], *, created_by: uuid.UUID | None) -> list[str]:
        command = SeedResourcePermissionsCommand(resources=resources, created_by=created_by)
        return await self._seed_use_case.execute(command)

    # -- role assignment (this permission's side) ---------------------------

    async def assign_to_role(
        self, permission_id: uuid.UUID, role_id: uuid.UUID, *, assigned_by: uuid.UUID | None
    ) -> None:
        command = AssignPermissionToRoleCommand(
            permission_id=permission_id, role_id=role_id, assigned_by=assigned_by
        )
        await self._assign_to_role_use_case.execute(command)

    async def remove_from_role(self, permission_id: uuid.UUID, role_id: uuid.UUID) -> None:
        command = RemovePermissionFromRoleCommand(permission_id=permission_id, role_id=role_id)
        await self._remove_from_role_use_case.execute(command)

    async def list_roles_for(self, permission_id: uuid.UUID) -> list[Role]:
        await self.get(permission_id)
        return await self._permissions.list_roles_for_permission(permission_id)

    # -- usage / lifecycle ---------------------------------------------------

    async def get_usage(self, permission_id: uuid.UUID) -> dict[str, int]:
        permission = await self.get(permission_id)
        direct_grantees = await self._permissions.list_direct_grant_user_ids(permission_id)
        role_grantees = await self._permissions.list_role_grantee_user_ids(permission_id)
        users_count = len(direct_grantees | role_grantees)
        roles_count = await self._permissions.count_roles_for_permission(permission_id)
        policies_count = await self._policies.count_for_resource_action(
            permission.resource, permission.action
        )
        return {
            "users_count": users_count,
            "roles_count": roles_count,
            "policies_count": policies_count,
        }

    async def set_status(
        self, permission_id: uuid.UUID, status: PermissionStatus, *, actor_id: uuid.UUID | None
    ) -> Permission:
        command = SetPermissionStatusCommand(permission_id=permission_id, status=status, actor_id=actor_id)
        return await self._set_status_use_case.execute(command)

    # -- audit history --------------------------------------------------------

    async def get_audit_history(self, permission_id: uuid.UUID) -> list[AuditLog]:
        await self.get(permission_id)
        rows = await self._audit_log.list_by_event_prefix("permission.")
        return [row for row in rows if row.context.get("permission_id") == str(permission_id)]
