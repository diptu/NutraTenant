from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.core.cache import PermissionCache
from app.infrastructure.database.associations import UserOrganizationRole
from app.modules.organizations.exceptions import (
    OrganizationNotFoundError,
    UserAlreadyMemberError,
)
from app.modules.organizations.repositories.interfaces.organization_repository import (
    OrganizationRepository,
)
from app.modules.organizations.schemas.commands.add_member_command import AddMemberCommand
from app.modules.organizations.use_cases._audit import record_organization_audit_event
from app.modules.organizations.use_cases._grant_guard import ensure_can_grant_role
from app.modules.roles.exceptions import RoleNotFoundError
from app.modules.roles.repositories.interfaces.role_repository import RoleRepository
from app.modules.users.exceptions import UserNotFoundError
from app.modules.users.repositories.sqlalchemy.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession


class AddMemberUseCase:
    def __init__(
        self,
        session: AsyncSession,
        orgs: OrganizationRepository,
        roles: RoleRepository,
        users: UserRepository,
        permission_cache: PermissionCache | None,
        audit_log: AuditLogRepository,
    ) -> None:
        self._session = session
        self._orgs = orgs
        self._roles = roles
        self._users = users
        self._permission_cache = permission_cache
        self._audit_log = audit_log

    async def execute(self, command: AddMemberCommand) -> UserOrganizationRole:
        org = await self._orgs.get_by_id(command.organization_id)
        if org is None:
            raise OrganizationNotFoundError(f"No organization with id '{command.organization_id}'")

        if await self._orgs.get_membership(command.organization_id, command.user_id) is not None:
            raise UserAlreadyMemberError("This user is already a member of this organization")

        user = await self._users.get_by_id(command.user_id)
        if user is None:
            raise UserNotFoundError(f"No user with id '{command.user_id}'")

        role = await self._roles.get_by_code_in_org(command.organization_id, command.role_code)
        if role is None:
            raise RoleNotFoundError(f"No role '{command.role_code}' exists in this organization")

        if command.invited_by is not None:
            await ensure_can_grant_role(
                self._orgs,
                self._roles,
                command.organization_id,
                granter_id=command.invited_by,
                target_role=role,
                permission_cache=self._permission_cache,
            )

        now = datetime.now(UTC)
        membership = UserOrganizationRole(
            id=uuid.uuid4(),
            organization_id=command.organization_id,
            user_id=command.user_id,
            role_id=role.id,
            invited_by=command.invited_by,
            is_active=True,
            joined_at=now,
            created_at=now,
            updated_at=now,
        )
        self._orgs.add_membership(membership)

        # Tenant-level attribute mapping: fill in any default_attributes key
        # the user doesn't already have — never overwrite a value the user
        # (or a more specific prior grant) already set.
        if org.default_attributes:
            user.attributes = {**org.default_attributes, **(user.attributes or {})}
            user.updated_at = now

        await self._session.flush()
        await record_organization_audit_event(
            self._session,
            self._audit_log,
            "tenant.member_added",
            command.invited_by,
            {
                "organization_id": str(command.organization_id),
                "user_id": str(command.user_id),
                "role_code": role.code,
            },
        )
        return membership
