"""User CRUD, search, activation, and ABAC attribute management."""

from __future__ import annotations

import uuid
from typing import cast

from app.audit import AuditLogRepository
from app.modules.organizations.repositories.sqlalchemy.organization_repository import (
    OrganizationRepository,
)
from app.modules.permissions.repositories.sqlalchemy.permission_repository import (
    PermissionRepository,
)
from app.modules.users.exceptions import UserNotFoundError
from app.modules.users.models import User, UserStatus
from app.modules.users.repositories.sqlalchemy.user_repository import (
    UserPermissionGrantRepository,
    UserRepository,
)
from app.modules.users.schemas.commands.add_user_permissions_command import (
    AddUserPermissionsCommand,
)
from app.modules.users.schemas.commands.delete_user_command import DeleteUserCommand
from app.modules.users.schemas.commands.remove_user_permissions_command import (
    RemoveUserPermissionsCommand,
)
from app.modules.users.schemas.commands.set_user_status_command import SetUserStatusCommand
from app.modules.users.schemas.commands.update_attributes_command import (
    UpdateAttributesCommand,
)
from app.modules.users.schemas.commands.update_profile_command import UpdateProfileCommand
from app.modules.users.schemas.commands.update_profile_settings_command import (
    UpdateProfileSettingsCommand,
)
from app.modules.users.schemas.dto.profile_context_dto import ProfileContext
from app.modules.users.use_cases.add_user_permissions import AddUserPermissionsUseCase
from app.modules.users.use_cases.delete_user import DeleteUserUseCase
from app.modules.users.use_cases.remove_user_permissions import RemoveUserPermissionsUseCase
from app.modules.users.use_cases.set_user_status import SetUserStatusUseCase
from app.modules.users.use_cases.update_attributes import UpdateAttributesUseCase
from app.modules.users.use_cases.update_profile import UpdateProfileUseCase
from app.modules.users.use_cases.update_profile_settings import UpdateProfileSettingsUseCase
from app.shared.utils.base_service import BaseService

__all__ = ["ProfileContext", "UserService", "account_status", "display_username"]


def display_username(user: User) -> str:
    """The real `username` column when set, else derived from the email's
    local part — used wherever a username needs to be rendered for an
    account that's never set one (see app.api.v1.users.routes/auth)."""
    return user.username or user.email.split("@", 1)[0]


def account_status(user: User) -> UserStatus:
    """Shared by the login response, GET /users/me, and PATCH .../status —
    just the stored `status` column now (see User.status). UserService.set_status
    is the one place that keeps it in lockstep with `is_active`/`locked_until`,
    so this stays the single source of truth instead of re-deriving it."""
    return cast(UserStatus, user.status)


class UserService(BaseService):
    def __init__(self, session) -> None:
        super().__init__(session)
        self._users = UserRepository(session)
        self._orgs = OrganizationRepository(session)
        self._permissions = PermissionRepository(session)
        self._user_permissions = UserPermissionGrantRepository(session)
        self._audit_log = AuditLogRepository(session)
        self._update_profile_use_case = UpdateProfileUseCase(session, self._users, self._audit_log)
        self._update_profile_settings_use_case = UpdateProfileSettingsUseCase(session, self._users)
        self._update_attributes_use_case = UpdateAttributesUseCase(session, self._users)
        self._set_status_use_case = SetUserStatusUseCase(session, self._users, self._audit_log)
        self._delete_use_case = DeleteUserUseCase(session, self._users, self._audit_log)
        self._add_permissions_use_case = AddUserPermissionsUseCase(
            session, self._users, self._orgs, self._permissions, self._user_permissions, self._audit_log
        )
        self._remove_permissions_use_case = RemoveUserPermissionsUseCase(
            session, self._users, self._orgs, self._permissions, self._user_permissions, self._audit_log
        )

    async def get_by_id(self, user_id: uuid.UUID) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(f"No user with id '{user_id}'")
        return user

    async def get_profile_context(self, user_id: uuid.UUID, tenant_slug: str | None) -> ProfileContext:
        if tenant_slug is None:
            return ProfileContext()

        organization = await self._orgs.get_by_slug(tenant_slug)
        if organization is None:
            return ProfileContext()

        membership = await self._orgs.get_membership(organization.id, user_id)
        if membership is None:
            return ProfileContext()

        role_codes = {p.code for p in membership.role.permissions}
        direct_grants = await self._user_permissions.list_for_user_in_organization(user_id, organization.id)
        direct_codes = {link.permission.code for link in direct_grants}
        return ProfileContext(
            organization=organization,
            role=membership.role,
            permissions=sorted(role_codes | direct_codes),
        )

    async def get_profile_context_for_user(
        self, user_id: uuid.UUID, tenant_slug: str | None
    ) -> ProfileContext:
        """Resolve tenant/role/permissions for GET /users/{user_id} — unlike
        get_profile_context (driven by the caller's own access-token
        tenant_id claim), there's no session to read a tenant from here, so
        `tenant_slug` is either given explicitly (disambiguates a user who
        belongs to several organizations) or falls back to that user's sole
        organization when they have exactly one. Deliberately never raises
        on ambiguity — this is a profile read, not a login."""
        if tenant_slug is not None:
            return await self.get_profile_context(user_id, tenant_slug)

        organizations = await self._orgs.list_for_user(user_id)
        if len(organizations) != 1:
            return ProfileContext()
        return await self.get_profile_context(user_id, organizations[0].slug)

    async def search(self, query: str | None, *, limit: int = 50, offset: int = 0) -> list[User]:
        if query:
            return await self._users.search(query, limit=limit)
        return await self._users.list_all(limit=limit, offset=offset)

    async def list_for_organization(
        self, organization_id: uuid.UUID, query: str | None, *, limit: int = 50, offset: int = 0
    ) -> list[User]:
        """Tenant-scoped counterpart to `search` — used by GET /users and
        GET /users/search when the caller is an org admin/owner rather than
        a superuser, so they only ever see their own tenant's users."""
        return await self._users.list_for_organization(organization_id, query, limit=limit, offset=offset)

    async def update_profile(
        self,
        user_id: uuid.UUID,
        *,
        full_name: str | None,
        username: str | None = None,
        phone: str | None = None,
        avatar_url: str | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> User:
        command = UpdateProfileCommand(
            user_id=user_id,
            full_name=full_name,
            username=username,
            phone=phone,
            avatar_url=avatar_url,
            actor_id=actor_id,
        )
        return await self._update_profile_use_case.execute(command)

    async def update_profile_settings(
        self,
        user_id: uuid.UUID,
        *,
        avatar_url: str | None = None,
        timezone: str | None = None,
        locale: str | None = None,
    ) -> User:
        command = UpdateProfileSettingsCommand(
            user_id=user_id, avatar_url=avatar_url, timezone=timezone, locale=locale
        )
        return await self._update_profile_settings_use_case.execute(command)

    async def update_attributes(self, user_id: uuid.UUID, patch: dict) -> User:
        command = UpdateAttributesCommand(user_id=user_id, patch=patch)
        return await self._update_attributes_use_case.execute(command)

    async def set_active(
        self, user_id: uuid.UUID, *, is_active: bool, actor_id: uuid.UUID | None = None
    ) -> User:
        """Pre-dates the `status` column (POST /users/{id}/activate|deactivate)
        — kept working as a simple boolean toggle, but routed through
        set_status so the two stay consistent rather than drifting apart."""
        return await self.set_status(user_id, "ACTIVE" if is_active else "INACTIVE", actor_id=actor_id)

    async def set_status(
        self, user_id: uuid.UUID, status: UserStatus, *, actor_id: uuid.UUID | None = None
    ) -> User:
        command = SetUserStatusCommand(user_id=user_id, status=status, actor_id=actor_id)
        return await self._set_status_use_case.execute(command)

    async def delete(self, user_id: uuid.UUID, *, actor_id: uuid.UUID | None = None) -> None:
        await self._delete_use_case.execute(DeleteUserCommand(user_id=user_id, actor_id=actor_id))

    # -- direct, org-scoped permission grants ----------------------------
    #
    # Independent of the Role/RolePermission graph — additive only, not
    # currently read by get_member_permissions or PolicyEngineService
    # (see app.infrastructure.database.associations.UserPermissionGrant).

    async def add_permissions(
        self,
        user_id: uuid.UUID,
        codes: list[str],
        *,
        tenant_slug: str | None,
        granted_by: uuid.UUID,
    ) -> list[str]:
        command = AddUserPermissionsCommand(
            user_id=user_id, codes=codes, tenant_slug=tenant_slug, granted_by=granted_by
        )
        return await self._add_permissions_use_case.execute(command)

    async def remove_permissions(
        self,
        user_id: uuid.UUID,
        codes: list[str],
        *,
        tenant_slug: str | None,
        actor_id: uuid.UUID | None = None,
    ) -> None:
        command = RemoveUserPermissionsCommand(
            user_id=user_id, codes=codes, tenant_slug=tenant_slug, actor_id=actor_id
        )
        await self._remove_permissions_use_case.execute(command)
