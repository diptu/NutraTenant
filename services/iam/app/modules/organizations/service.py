"""Organization lifecycle, membership management, and tenant-level attribute mapping.

Membership is intentionally limited to the roles an organization is
auto-provisioned with at creation (``owner``, ``admin``, ``member``,
``viewer``) — full custom role management is a separate concern (role CRUD)
not built here. ``owner`` stays the one structural role (the bypass in
``app.modules.organizations.use_cases._grant_guard``, the last-owner
protections, ...) — ``admin`` is just a regular grantable role with no
permissions attached by default, not a second structural tier.
"""

from __future__ import annotations

import uuid

from app.audit import AuditLogRepository
from app.core.cache import PermissionCache
from app.core.config import Settings, get_settings
from app.infrastructure.database.associations import UserOrganizationRole
from app.modules.organizations.exceptions import OrganizationNotFoundError
from app.modules.organizations.models import Organization, OrganizationInvitation
from app.modules.organizations.repositories.sqlalchemy.organization_repository import (
    OrganizationInvitationRepository,
    OrganizationRepository,
)
from app.modules.organizations.schemas.commands.accept_invitation_command import (
    AcceptInvitationCommand,
)
from app.modules.organizations.schemas.commands.add_member_command import AddMemberCommand
from app.modules.organizations.schemas.commands.create_organization_command import (
    CreateOrganizationCommand,
)
from app.modules.organizations.schemas.commands.delete_organization_command import (
    DeleteOrganizationCommand,
)
from app.modules.organizations.schemas.commands.invite_member_command import (
    InviteMemberCommand,
)
from app.modules.organizations.schemas.commands.remove_member_command import (
    RemoveMemberCommand,
)
from app.modules.organizations.schemas.commands.revoke_invitation_command import (
    RevokeInvitationCommand,
)
from app.modules.organizations.schemas.commands.update_member_role_command import (
    UpdateMemberRoleCommand,
)
from app.modules.organizations.schemas.commands.update_organization_command import (
    UpdateOrganizationCommand,
)
from app.modules.organizations.use_cases.accept_invitation import AcceptInvitationUseCase
from app.modules.organizations.use_cases.add_member import AddMemberUseCase
from app.modules.organizations.use_cases.create_organization import CreateOrganizationUseCase
from app.modules.organizations.use_cases.delete_organization import DeleteOrganizationUseCase
from app.modules.organizations.use_cases.invite_member import InviteMemberUseCase
from app.modules.organizations.use_cases.remove_member import RemoveMemberUseCase
from app.modules.organizations.use_cases.revoke_invitation import RevokeInvitationUseCase
from app.modules.organizations.use_cases.update_member_role import UpdateMemberRoleUseCase
from app.modules.organizations.use_cases.update_organization import UpdateOrganizationUseCase
from app.modules.reserved_tenant_ids.repositories.sqlalchemy.reserved_tenant_id_repository import (
    ReservedTenantIdRepository,
)
from app.modules.roles.models import Role
from app.modules.roles.repositories.sqlalchemy.role_repository import RoleRepository
from app.modules.roles.service import resolve_role_in_org
from app.modules.tenants.repositories.sqlalchemy.tenant_repository import (
    OrganizationTenantRepository,
)
from app.modules.users.repositories.sqlalchemy.user_repository import UserRepository
from app.shared.exceptions.base import ForbiddenError


class OrganizationService:
    def __init__(
        self,
        session,
        permission_cache: PermissionCache | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._permission_cache = permission_cache
        self._settings = settings or get_settings()
        self._orgs = OrganizationRepository(session)
        self._roles = RoleRepository(session)
        self._users = UserRepository(session)
        self._invitations = OrganizationInvitationRepository(session)
        self._audit_log = AuditLogRepository(session)
        self._org_tenants = OrganizationTenantRepository(session)
        self._reserved_tenant_ids = ReservedTenantIdRepository(session)
        self._create_use_case = CreateOrganizationUseCase(
            session, self._orgs, self._roles, self._reserved_tenant_ids
        )
        self._update_use_case = UpdateOrganizationUseCase(session, self._orgs)
        self._delete_use_case = DeleteOrganizationUseCase(session, self._orgs, self._org_tenants)
        self._add_member_use_case = AddMemberUseCase(
            session, self._orgs, self._roles, self._users, self._permission_cache, self._audit_log
        )
        self._remove_member_use_case = RemoveMemberUseCase(session, self._orgs, self._audit_log)
        self._update_member_role_use_case = UpdateMemberRoleUseCase(
            session, self._orgs, self._roles, self._permission_cache
        )
        self._invite_member_use_case = InviteMemberUseCase(
            session,
            self._orgs,
            self._roles,
            self._users,
            self._invitations,
            self._audit_log,
            self._permission_cache,
            self._settings,
        )
        self._revoke_invitation_use_case = RevokeInvitationUseCase(session, self._invitations)
        self._accept_invitation_use_case = AcceptInvitationUseCase(
            session, self._invitations, self._add_member_use_case, self._audit_log
        )

    # -- lifecycle -------------------------------------------------------

    async def create(
        self, *, name: str, slug: str, description: str | None, owner_id: uuid.UUID
    ) -> Organization:
        command = CreateOrganizationCommand(name=name, slug=slug, description=description, owner_id=owner_id)
        return await self._create_use_case.execute(command)

    async def get(self, organization_id: uuid.UUID) -> Organization:
        org = await self._orgs.get_by_id(organization_id)
        if org is None:
            raise OrganizationNotFoundError(f"No organization with id '{organization_id}'")
        return org

    async def get_by_slug(self, slug: str) -> Organization:
        org = await self._orgs.get_by_slug(slug)
        if org is None:
            raise OrganizationNotFoundError(f"No tenant '{slug}'")
        return org

    async def resolve_role(self, organization_id: uuid.UUID, role: str) -> Role | None:
        """Resolves a free-form role string (a `code` or a display `name`)
        to this organization's Role — see app.modules.roles.service."""
        return await resolve_role_in_org(self._roles, organization_id, role)

    async def list_for_user(self, user_id: uuid.UUID) -> list[Organization]:
        return await self._orgs.list_for_user(user_id)

    async def update(
        self,
        organization_id: uuid.UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        default_attributes: dict | None = None,
        is_reserved: bool | None = None,
    ) -> Organization:
        command = UpdateOrganizationCommand(
            organization_id=organization_id,
            name=name,
            description=description,
            default_attributes=default_attributes,
            is_reserved=is_reserved,
        )
        return await self._update_use_case.execute(command)

    async def delete(self, organization_id: uuid.UUID) -> None:
        await self._delete_use_case.execute(DeleteOrganizationCommand(organization_id=organization_id))

    # -- membership -------------------------------------------------------

    async def require_membership(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> UserOrganizationRole:
        membership = await self._orgs.get_membership(organization_id, user_id)
        if membership is None:
            raise ForbiddenError("You are not a member of this organization")
        return membership

    async def require_owner(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> UserOrganizationRole:
        membership = await self.require_membership(organization_id, user_id)
        if membership.role.code != "owner":
            raise ForbiddenError("Only the organization owner can perform this action")
        return membership

    async def list_members(self, organization_id: uuid.UUID) -> list[UserOrganizationRole]:
        await self.get(organization_id)
        return await self._orgs.list_members(organization_id)

    async def add_member(
        self,
        organization_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        role_code: str = "member",
        invited_by: uuid.UUID | None,
    ) -> UserOrganizationRole:
        command = AddMemberCommand(
            organization_id=organization_id,
            user_id=user_id,
            role_code=role_code,
            invited_by=invited_by,
        )
        return await self._add_member_use_case.execute(command)

    async def remove_member(
        self, organization_id: uuid.UUID, user_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
    ) -> None:
        command = RemoveMemberCommand(organization_id=organization_id, user_id=user_id, actor_id=actor_id)
        await self._remove_member_use_case.execute(command)

    async def update_member_role(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        new_role_code: str,
        actor_id: uuid.UUID,
    ) -> UserOrganizationRole:
        command = UpdateMemberRoleCommand(
            organization_id=organization_id,
            user_id=user_id,
            new_role_code=new_role_code,
            actor_id=actor_id,
        )
        return await self._update_member_role_use_case.execute(command)

    # -- invitations -------------------------------------------------------

    async def invite_member(
        self,
        organization_id: uuid.UUID,
        *,
        email: str,
        role_code: str = "member",
        invited_by: uuid.UUID,
        always_reveal_token: bool = False,
    ) -> tuple[OrganizationInvitation, str | None]:
        command = InviteMemberCommand(
            organization_id=organization_id,
            email=email,
            role_code=role_code,
            invited_by=invited_by,
            always_reveal_token=always_reveal_token,
        )
        return await self._invite_member_use_case.execute(command)

    async def list_pending_invitations(self, organization_id: uuid.UUID) -> list[OrganizationInvitation]:
        await self.get(organization_id)  # 404s first if the org doesn't exist
        return await self._invitations.list_pending_for_org(organization_id)

    async def revoke_invitation(self, organization_id: uuid.UUID, invitation_id: uuid.UUID) -> None:
        command = RevokeInvitationCommand(organization_id=organization_id, invitation_id=invitation_id)
        await self._revoke_invitation_use_case.execute(command)

    async def accept_invitation(
        self, *, raw_token: str, accepting_user_id: uuid.UUID, accepting_email: str
    ) -> tuple[UserOrganizationRole, str]:
        command = AcceptInvitationCommand(
            raw_token=raw_token,
            accepting_user_id=accepting_user_id,
            accepting_email=accepting_email,
        )
        return await self._accept_invitation_use_case.execute(command)
