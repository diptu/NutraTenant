from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.infrastructure.database.associations import UserPermissionGrant
from app.modules.organizations.repositories.interfaces.organization_repository import (
    OrganizationRepository,
)
from app.modules.permissions.exceptions import PermissionNotFoundError
from app.modules.permissions.repositories.interfaces.permission_repository import (
    PermissionRepository,
)
from app.modules.users.repositories.interfaces.user_repository import (
    UserPermissionGrantRepository,
    UserRepository,
)
from app.modules.users.schemas.commands.add_user_permissions_command import (
    AddUserPermissionsCommand,
)
from app.modules.users.use_cases._audit import record_user_audit_event
from app.modules.users.use_cases._grants import (
    list_direct_permission_codes,
    resolve_organization_for_grant,
)
from app.modules.users.use_cases._lookups import get_user
from sqlalchemy.ext.asyncio import AsyncSession


class AddUserPermissionsUseCase:
    """POST /users/{user_id}/permissions — idempotent: granting a
    permission the user already directly holds is a no-op, not a
    conflict. Returns the user's full direct-grant set for that
    organization (not just the codes just added)."""

    def __init__(
        self,
        session: AsyncSession,
        users: UserRepository,
        orgs: OrganizationRepository,
        permissions: PermissionRepository,
        user_permissions: UserPermissionGrantRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._session = session
        self._users = users
        self._orgs = orgs
        self._permissions = permissions
        self._user_permissions = user_permissions
        self._audit_log = audit_log

    async def execute(self, command: AddUserPermissionsCommand) -> list[str]:
        await get_user(self._users, command.user_id)
        organization = await resolve_organization_for_grant(
            self._orgs, command.user_id, command.tenant_slug
        )

        now = datetime.now(UTC)
        granted_codes: list[str] = []
        for code in command.codes:
            permission = await self._permissions.get_by_code(code)
            if permission is None:
                raise PermissionNotFoundError(f"No permission with code '{code}'")
            existing = await self._user_permissions.get_link(
                command.user_id, organization.id, permission.id
            )
            if existing is None:
                self._user_permissions.add_link(
                    UserPermissionGrant(
                        id=uuid.uuid4(),
                        user_id=command.user_id,
                        organization_id=organization.id,
                        permission_id=permission.id,
                        granted_by=command.granted_by,
                        created_at=now,
                    )
                )
                granted_codes.append(code)
        await self._session.flush()
        if granted_codes:
            await record_user_audit_event(
                self._session,
                self._audit_log,
                "permission.assigned",
                command.granted_by,
                {
                    "user_id": str(command.user_id),
                    "organization_id": str(organization.id),
                    "codes": granted_codes,
                },
            )
        else:
            await self._session.commit()
        return await list_direct_permission_codes(self._user_permissions, command.user_id, organization.id)
