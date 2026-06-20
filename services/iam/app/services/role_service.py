"""Coarse-grained, platform-wide (non-org-scoped) role management.

Distinct from app.services.organization_service's tenant-scoped owner/member
roles — these are global roles (Admin/Member/Guest, ...) assigned directly
to a user via the ``user_roles`` table, used by the fast-path RBAC guard
(app.api.v1.dependencies.require_global_role) before any ABAC evaluation
even runs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError

from app.domain.exceptions import (
    AlreadyExistsError,
    ForbiddenError,
    PermissionNotFoundError,
    RoleAlreadyExistsError,
    RoleInUseError,
    RoleNotAssignedError,
    RoleNotFoundError,
    UserNotFoundError,
)
from app.infrastructure.db.models.associations import RolePermission
from app.infrastructure.db.models.audit_log import AuditLog
from app.infrastructure.db.models.role import Role
from app.infrastructure.db.models.user_role import UserRole
from app.infrastructure.db.repositories.audit_repo import AuditLogRepository
from app.infrastructure.db.repositories.permission_repo import PermissionRepository
from app.infrastructure.db.repositories.role_repo import RoleRepository
from app.infrastructure.db.repositories.user_repo import UserRepository
from app.infrastructure.db.repositories.user_role_repo import UserRoleRepository

DEFAULT_GLOBAL_ROLES = (
    ("admin", "Admin", "Platform-wide administrator"),
    ("member", "Member", "Standard platform member"),
    ("guest", "Guest", "Limited, read-mostly access"),
)


class RoleService:
    def __init__(self, session) -> None:
        self._session = session
        self._roles = RoleRepository(session)
        self._user_roles = UserRoleRepository(session)
        self._users = UserRepository(session)
        self._permissions = PermissionRepository(session)
        self._audit_log = AuditLogRepository(session)

    # -- catalog -----------------------------------------------------------

    async def seed_defaults(self) -> list[Role]:
        """Idempotent — safe to call on every app startup or test setup."""
        roles = []
        now = datetime.now(UTC)
        for code, name, description in DEFAULT_GLOBAL_ROLES:
            role = await self._roles.get_by_code(code)
            if role is None:
                role = Role(
                    id=uuid.uuid4(),
                    name=name,
                    code=code,
                    description=description,
                    organization_id=None,
                    is_system=True,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                self._roles.add(role)
            roles.append(role)
        await self._session.commit()
        return roles

    async def list_roles(self) -> list[Role]:
        return await self._roles.list_all_global()

    async def get_role(self, role_id: uuid.UUID) -> Role:
        """Global (organization_id IS NULL) roles only — used by the
        platform-wide role catalog endpoints."""
        role = await self._roles.get_by_id(role_id)
        if role is None or role.organization_id is not None:
            raise RoleNotFoundError(f"No global role with id '{role_id}'")
        return role

    async def get_any_role(self, role_id: uuid.UUID) -> Role:
        """Global *or* org-scoped — used by lookups/mutations that work on
        either (permission assignment, generic by-id retrieval)."""
        role = await self._roles.get_by_id(role_id)
        if role is None:
            raise RoleNotFoundError(f"No role with id '{role_id}'")
        return role

    async def create_role(
        self,
        *,
        name: str,
        code: str,
        description: str | None,
        organization_id: uuid.UUID | None = None,
    ) -> Role:
        existing = (
            await self._roles.get_by_code(code)
            if organization_id is None
            else await self._roles.get_by_code_in_org(organization_id, code)
        )
        if existing is not None:
            raise RoleAlreadyExistsError(f"A role with code '{code}' already exists")

        now = datetime.now(UTC)
        role = Role(
            id=uuid.uuid4(),
            name=name,
            code=code,
            description=description,
            organization_id=organization_id,
            is_system=False,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self._roles.add(role)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise RoleAlreadyExistsError(
                f"A role with code '{code}' already exists"
            ) from exc

        await self._session.commit()
        return role

    async def update_role(
        self,
        role_id: uuid.UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        is_active: bool | None = None,
    ) -> Role:
        role = await self.get_any_role(role_id)
        if role.is_system:
            raise ForbiddenError("System roles cannot be modified")

        if name is not None:
            role.name = name
        if description is not None:
            role.description = description
        if is_active is not None:
            role.is_active = is_active
        role.updated_at = datetime.now(UTC)

        await self._session.commit()
        return role

    async def delete_role(self, role_id: uuid.UUID) -> None:
        role = await self.get_any_role(role_id)
        if role.is_system:
            raise ForbiddenError("System roles cannot be deleted")
        if await self._roles.is_in_use(role_id):
            raise RoleInUseError("This role is still assigned to at least one user")
        await self._roles.delete(role)
        await self._session.commit()

    # -- permission assignment (the role's own grants, not a user's) -------

    async def add_permissions(
        self, role_id: uuid.UUID, codes: list[str], *, assigned_by: uuid.UUID
    ) -> Role:
        role = await self.get_any_role(role_id)
        if role.is_system:
            raise ForbiddenError("System roles cannot be modified")

        now = datetime.now(UTC)
        for code in codes:
            permission = await self._permissions.get_by_code(code)
            if permission is None:
                raise PermissionNotFoundError(f"No permission with code '{code}'")
            link = await self._permissions.get_role_permission(role.id, permission.id)
            if link is None:
                self._permissions.add_role_permission(
                    RolePermission(
                        id=uuid.uuid4(),
                        role_id=role.id,
                        permission_id=permission.id,
                        assigned_by=assigned_by,
                        created_at=now,
                    )
                )

        # Bust app.core.cache permission-cache entries keyed on this role.
        role.updated_at = now
        await self._session.commit()
        reloaded = await self._roles.get_with_permissions(role.id)
        assert reloaded is not None
        return reloaded

    async def remove_permission(
        self, role_id: uuid.UUID, permission_id: uuid.UUID
    ) -> Role:
        role = await self.get_any_role(role_id)
        if role.is_system:
            raise ForbiddenError("System roles cannot be modified")

        link = await self._permissions.get_role_permission(role.id, permission_id)
        if link is None:
            raise PermissionNotFoundError("This role does not have that permission")
        await self._permissions.remove_role_permission(link)

        role.updated_at = datetime.now(UTC)
        await self._session.commit()
        reloaded = await self._roles.get_with_permissions(role.id)
        assert reloaded is not None
        return reloaded

    # -- assignment ----------------------------------------------------------

    async def assign_role(
        self, *, user_id: uuid.UUID, role_id: uuid.UUID, assigned_by: uuid.UUID | None
    ) -> UserRole:
        role = await self.get_role(role_id)
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(f"No user with id '{user_id}'")
        if await self._user_roles.has_role(user_id, role_id):
            raise AlreadyExistsError(f"User already has the '{role.code}' role")

        now = datetime.now(UTC)
        assignment = UserRole(
            id=uuid.uuid4(),
            user_id=user_id,
            role_id=role_id,
            assigned_by=assigned_by,
            assigned_at=now,
            created_at=now,
            updated_at=now,
        )
        self._user_roles.add(assignment)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise AlreadyExistsError(
                f"User already has the '{role.code}' role"
            ) from exc

        await self._audit(
            event_type="rbac.role.assigned",
            user_id=user_id,
            context={
                "role_code": role.code,
                "assigned_by": str(assigned_by) if assigned_by else None,
            },
        )
        return assignment

    async def revoke_role(self, *, user_id: uuid.UUID, role_id: uuid.UUID) -> None:
        role = await self.get_role(role_id)
        assignment = await self._user_roles.get(user_id, role_id)
        if assignment is None:
            raise RoleNotAssignedError(f"User does not have the '{role.code}' role")
        await self._user_roles.delete(assignment)
        await self._audit(
            event_type="rbac.role.revoked",
            user_id=user_id,
            context={"role_code": role.code},
        )

    async def list_user_roles(self, user_id: uuid.UUID) -> list[UserRole]:
        return await self._user_roles.list_for_user(user_id)

    async def has_role(self, user_id: uuid.UUID, code: str) -> bool:
        role = await self._roles.get_by_code(code)
        if role is None:
            return False
        return await self._user_roles.has_role(user_id, role.id)

    async def _audit(
        self, *, event_type: str, user_id: uuid.UUID, context: dict
    ) -> None:
        self._audit_log.add(
            AuditLog(
                id=uuid.uuid4(),
                user_id=user_id,
                event_type=event_type,
                context=context,
                created_at=datetime.now(UTC),
            )
        )
        await self._session.commit()
