from __future__ import annotations

from datetime import UTC, datetime

from app.core.cache import PermissionCache
from app.infrastructure.database.associations import UserOrganizationRole
from app.modules.organizations.exceptions import LastOwnerError
from app.modules.organizations.repositories.interfaces.organization_repository import (
    OrganizationRepository,
)
from app.modules.organizations.schemas.commands.update_member_role_command import (
    UpdateMemberRoleCommand,
)
from app.modules.organizations.use_cases._grant_guard import ensure_can_grant_role
from app.modules.roles.exceptions import RoleNotFoundError
from app.modules.roles.repositories.interfaces.role_repository import RoleRepository
from app.modules.users.exceptions import UserNotFoundError
from sqlalchemy.ext.asyncio import AsyncSession


class UpdateMemberRoleUseCase:
    def __init__(
        self,
        session: AsyncSession,
        orgs: OrganizationRepository,
        roles: RoleRepository,
        permission_cache: PermissionCache | None,
    ) -> None:
        self._session = session
        self._orgs = orgs
        self._roles = roles
        self._permission_cache = permission_cache

    async def execute(self, command: UpdateMemberRoleCommand) -> UserOrganizationRole:
        membership = await self._orgs.get_membership(command.organization_id, command.user_id)
        if membership is None:
            raise UserNotFoundError("This user is not a member of this organization")

        new_role = await self._roles.get_by_code_in_org(command.organization_id, command.new_role_code)
        if new_role is None:
            raise RoleNotFoundError(f"No role '{command.new_role_code}' exists in this organization")

        await ensure_can_grant_role(
            self._orgs,
            self._roles,
            command.organization_id,
            granter_id=command.actor_id,
            target_role=new_role,
            permission_cache=self._permission_cache,
        )

        if membership.role.code == "owner" and new_role.code != "owner":
            if await self._orgs.count_owners(command.organization_id) <= 1:
                raise LastOwnerError("Cannot demote the organization's last owner")

        membership.role_id = new_role.id
        membership.updated_at = datetime.now(UTC)
        await self._session.commit()

        # `membership.role` is still the *old* Role object in the session's
        # identity map — changing role_id directly doesn't refresh a
        # selectinload-populated relationship on its own. Expire so the
        # re-fetch below actually reloads it instead of returning the stale
        # cached relationship.
        self._session.expire(membership)
        refreshed = await self._orgs.get_membership(command.organization_id, command.user_id)
        assert refreshed is not None
        return refreshed
