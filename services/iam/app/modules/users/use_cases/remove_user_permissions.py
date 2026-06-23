from __future__ import annotations

from app.audit import AuditLogRepository
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
from app.modules.users.schemas.commands.remove_user_permissions_command import (
    RemoveUserPermissionsCommand,
)
from app.modules.users.use_cases._audit import record_user_audit_event
from app.modules.users.use_cases._grants import resolve_organization_for_grant
from app.modules.users.use_cases._lookups import get_user
from sqlalchemy.ext.asyncio import AsyncSession


class RemoveUserPermissionsUseCase:
    """DELETE /users/{user_id}/permissions — idempotent: removing a
    permission the user doesn't directly hold is a no-op, not an error
    (only an unknown *code* is)."""

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

    async def execute(self, command: RemoveUserPermissionsCommand) -> None:
        await get_user(self._users, command.user_id)
        organization = await resolve_organization_for_grant(
            self._orgs, command.user_id, command.tenant_slug
        )

        removed_codes: list[str] = []
        for code in command.codes:
            permission = await self._permissions.get_by_code(code)
            if permission is None:
                raise PermissionNotFoundError(f"No permission with code '{code}'")
            link = await self._user_permissions.get_link(command.user_id, organization.id, permission.id)
            if link is not None:
                await self._user_permissions.remove_link(link)
                removed_codes.append(code)
        await self._session.flush()
        if removed_codes:
            await record_user_audit_event(
                self._session,
                self._audit_log,
                "permission.removed",
                command.actor_id,
                {
                    "user_id": str(command.user_id),
                    "organization_id": str(organization.id),
                    "codes": removed_codes,
                },
            )
        else:
            await self._session.commit()
