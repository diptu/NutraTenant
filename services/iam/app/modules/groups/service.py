"""Group CRUD (incl. parent hierarchy) and group-membership CRUD — backs the
Groups & Group Memberships API (POST/GET/PATCH/DELETE /groups,
.../group-memberships).

A membership has no tenant column of its own (see
app.modules.groups.models) — its tenant is always its group's tenant, so
every membership operation resolves/validates the caller-given
``organization_id`` against the target group rather than trusting a
second, possibly-drifted copy.

Tenant resolution and the owner-or-superuser / member-or-superuser
authorization decisions also live here rather than in the route layer
(app.api.v1.groups.routes / membership_routes) — those routes only parse
the request and shape the response; every "is this allowed" call goes
through this service, which composes :class:`OrganizationService` the same
way app.modules.auth.google_service.GoogleOAuthService composes AuthService.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.audit import AuditLogRepository
from app.modules.groups.exceptions import (
    GroupMembershipNotFoundError,
    GroupNotFoundError,
    GroupTenantRequiredError,
)
from app.modules.groups.models import Group, GroupMembership
from app.modules.groups.repositories.sqlalchemy.group_repository import (
    GroupMembershipRepository,
    GroupRepository,
)
from app.modules.groups.schemas.commands.bulk_add_group_members_command import (
    BulkAddGroupMembersCommand,
)
from app.modules.groups.schemas.commands.create_group_command import CreateGroupCommand
from app.modules.groups.schemas.commands.create_group_membership_command import (
    CreateGroupMembershipCommand,
)
from app.modules.groups.schemas.commands.delete_group_command import DeleteGroupCommand
from app.modules.groups.schemas.commands.delete_group_membership_command import (
    DeleteGroupMembershipCommand,
)
from app.modules.groups.schemas.commands.remove_group_member_command import (
    RemoveGroupMemberCommand,
)
from app.modules.groups.schemas.commands.update_group_command import UpdateGroupCommand
from app.modules.groups.schemas.commands.update_group_membership_command import (
    UpdateGroupMembershipCommand,
)
from app.modules.groups.use_cases.bulk_add_group_members import BulkAddGroupMembersUseCase
from app.modules.groups.use_cases.create_group import CreateGroupUseCase
from app.modules.groups.use_cases.create_group_membership import CreateGroupMembershipUseCase
from app.modules.groups.use_cases.delete_group import DeleteGroupUseCase
from app.modules.groups.use_cases.delete_group_membership import DeleteGroupMembershipUseCase
from app.modules.groups.use_cases.remove_group_member import RemoveGroupMemberUseCase
from app.modules.groups.use_cases.update_group import UpdateGroupUseCase
from app.modules.groups.use_cases.update_group_membership import UpdateGroupMembershipUseCase
from app.modules.groups.value_objects import (
    GroupMembershipRole,
    GroupMembershipStatus,
    GroupMembershipType,
    GroupStatus,
    GroupType,
)
from app.modules.organizations.service import OrganizationService
from app.modules.users.models import User
from app.modules.users.repositories.sqlalchemy.user_repository import UserRepository
from app.shared.exceptions.base import ForbiddenError


class GroupService:
    def __init__(self, session, *, org_service: OrganizationService) -> None:
        self._session = session
        self._org_service = org_service
        self._groups = GroupRepository(session)
        self._memberships = GroupMembershipRepository(session)
        self._users = UserRepository(session)
        self._audit_log = AuditLogRepository(session)
        self._create_group_use_case = CreateGroupUseCase(session, self._groups, self._audit_log)
        self._update_group_use_case = UpdateGroupUseCase(session, self._groups, self._audit_log)
        self._delete_group_use_case = DeleteGroupUseCase(session, self._groups, self._audit_log)
        self._create_membership_use_case = CreateGroupMembershipUseCase(
            session, self._groups, self._memberships, self._users, self._audit_log
        )
        self._bulk_add_members_use_case = BulkAddGroupMembersUseCase(
            session, self._groups, self._memberships, self._users, self._audit_log
        )
        self._remove_member_use_case = RemoveGroupMemberUseCase(
            session, self._memberships, self._audit_log
        )
        self._update_membership_use_case = UpdateGroupMembershipUseCase(
            session, self._memberships, self._audit_log
        )
        self._delete_membership_use_case = DeleteGroupMembershipUseCase(
            session, self._memberships, self._audit_log
        )

    # -- tenant resolution -----------------------------------------------------

    async def resolve_required_tenant(
        self, *, tenant_id: str | None, session_tenant_id: str | None
    ) -> uuid.UUID:
        """A group always needs *some* tenant — there is no global group, so
        an unresolvable tenant (no explicit ``tenant_id`` and no tenant on
        the caller's session) is an error rather than "global", unlike the
        equivalent helper in app.api.v1.roles.routes."""
        effective = tenant_id or session_tenant_id
        if effective is None:
            raise GroupTenantRequiredError("tenant_id is required to manage groups")
        organization = await self._org_service.get_by_slug(effective)
        return organization.id

    async def resolve_optional_tenant(
        self, *, tenant_id: str | None, session_tenant_id: str | None
    ) -> uuid.UUID | None:
        effective = tenant_id or session_tenant_id
        if effective is None:
            return None
        organization = await self._org_service.get_by_slug(effective)
        return organization.id

    # -- authorization -----------------------------------------------------------

    async def ensure_can_create_group(self, organization_id: uuid.UUID, current_user: User) -> None:
        if current_user.is_superuser:
            return
        await self._org_service.require_owner(organization_id, current_user.id)

    async def ensure_can_manage_group(self, group: Group, current_user: User) -> None:
        if current_user.is_superuser:
            return
        await self._org_service.require_owner(group.organization_id, current_user.id)

    async def ensure_can_list_groups(self, organization_id: uuid.UUID, current_user: User) -> None:
        if current_user.is_superuser:
            return
        await self._org_service.require_membership(organization_id, current_user.id)

    async def ensure_can_create_membership(self, group: Group, current_user: User) -> None:
        """Same gate as managing the group itself — adding/removing members
        is a tenant-admin action, not something every group member can do."""
        await self.ensure_can_manage_group(group, current_user)

    async def ensure_can_manage_membership(self, membership: GroupMembership, current_user: User) -> None:
        if current_user.is_superuser:
            return
        group = await self.get_group(membership.group_id)
        await self._org_service.require_owner(group.organization_id, current_user.id)

    async def ensure_can_list_memberships(
        self,
        *,
        group_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        current_user: User,
    ) -> None:
        """Mirrors the gating ``GET /api/v1/group-memberships`` documents:
        filtering by ``group_id`` requires tenant membership in that group's
        org; filtering by ``user_id`` alone is self-or-superuser; with
        neither filter, only a superuser may list platform-wide."""
        if current_user.is_superuser:
            return
        if group_id is not None:
            group = await self.get_group(group_id)
            await self._org_service.require_membership(group.organization_id, current_user.id)
        elif user_id is not None:
            if current_user.id != user_id:
                raise ForbiddenError("You can only view your own group memberships")
        else:
            raise ForbiddenError("This action requires administrator privileges")

    # -- Group CRUD ----------------------------------------------------------

    async def create_group(
        self,
        *,
        name: str,
        description: str | None,
        organization_id: uuid.UUID,
        type: GroupType,
        parent_group_id: uuid.UUID | None,
        attributes: dict,
        metadata: dict,
        created_by: uuid.UUID | None,
    ) -> Group:
        command = CreateGroupCommand(
            name=name,
            description=description,
            organization_id=organization_id,
            type=type,
            parent_group_id=parent_group_id,
            attributes=attributes,
            metadata=metadata,
            created_by=created_by,
        )
        return await self._create_group_use_case.execute(command)

    async def get_group(self, group_id: uuid.UUID) -> Group:
        group = await self._groups.get_by_id(group_id)
        if group is None:
            raise GroupNotFoundError(f"No group with id '{group_id}'")
        return group

    async def get_group_in_org(self, group_id: uuid.UUID, organization_id: uuid.UUID) -> Group:
        """Same as :meth:`get_group`, but also enforces tenant scope — used by
        the membership flows so a caller can't reference a group from a
        different tenant by id, and so the 404 leaks no signal either way."""
        group = await self.get_group(group_id)
        if group.organization_id != organization_id:
            raise GroupNotFoundError(f"No group with id '{group_id}'")
        return group

    async def list_paginated(
        self,
        *,
        organization_id: uuid.UUID,
        page: int,
        page_size: int,
        type: str | None,
        status: str | None,
        parent_group_id: uuid.UUID | None,
        search: str | None,
    ) -> tuple[list[Group], int]:
        offset = (page - 1) * page_size
        return await self._groups.search_catalog(
            organization_id=organization_id,
            type=type,
            status=status,
            parent_group_id=parent_group_id,
            search=search,
            limit=page_size,
            offset=offset,
        )

    async def update_group(
        self,
        group_id: uuid.UUID,
        *,
        name: str | None,
        description: str | None,
        type: GroupType | None,
        status: GroupStatus | None,
        parent_group_id: uuid.UUID | None,
        attributes: dict | None,
        metadata: dict | None,
        updated_by: uuid.UUID | None,
    ) -> Group:
        command = UpdateGroupCommand(
            group_id=group_id,
            name=name,
            description=description,
            type=type,
            status=status,
            parent_group_id=parent_group_id,
            attributes=attributes,
            metadata=metadata,
            updated_by=updated_by,
        )
        return await self._update_group_use_case.execute(command)

    async def delete_group(self, group_id: uuid.UUID) -> None:
        await self._delete_group_use_case.execute(DeleteGroupCommand(group_id=group_id))

    async def count_members(self, group_id: uuid.UUID) -> int:
        return await self._groups.count_members(group_id)

    # -- GroupMembership CRUD -------------------------------------------------

    async def create_membership(
        self,
        *,
        user_id: uuid.UUID,
        group_id: uuid.UUID,
        organization_id: uuid.UUID,
        membership_type: GroupMembershipType,
        role: GroupMembershipRole,
        expires_at: datetime | None,
        attributes: dict,
        created_by: uuid.UUID | None,
    ) -> GroupMembership:
        command = CreateGroupMembershipCommand(
            user_id=user_id,
            group_id=group_id,
            organization_id=organization_id,
            membership_type=membership_type,
            role=role,
            expires_at=expires_at,
            attributes=attributes,
            created_by=created_by,
        )
        return await self._create_membership_use_case.execute(command)

    async def bulk_add_members(
        self,
        group_id: uuid.UUID,
        user_ids: list[uuid.UUID],
        *,
        organization_id: uuid.UUID,
        created_by: uuid.UUID | None,
    ) -> int:
        command = BulkAddGroupMembersCommand(
            group_id=group_id,
            user_ids=user_ids,
            organization_id=organization_id,
            created_by=created_by,
        )
        return await self._bulk_add_members_use_case.execute(command)

    async def remove_member_by_user(self, group_id: uuid.UUID, user_id: uuid.UUID) -> None:
        command = RemoveGroupMemberCommand(group_id=group_id, user_id=user_id)
        await self._remove_member_use_case.execute(command)

    async def get_membership(self, membership_id: uuid.UUID) -> GroupMembership:
        membership = await self._memberships.get_by_id(membership_id)
        if membership is None:
            raise GroupMembershipNotFoundError(f"No group membership with id '{membership_id}'")
        return membership

    async def list_memberships_paginated(
        self,
        *,
        group_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[GroupMembership], int]:
        offset = (page - 1) * page_size
        return await self._memberships.search(
            group_id=group_id,
            user_id=user_id,
            status=status,
            limit=page_size,
            offset=offset,
        )

    async def update_membership(
        self,
        membership_id: uuid.UUID,
        *,
        role: GroupMembershipRole | None,
        status: GroupMembershipStatus | None,
        expires_at: datetime | None,
        attributes: dict | None,
        updated_by: uuid.UUID | None,
    ) -> GroupMembership:
        command = UpdateGroupMembershipCommand(
            membership_id=membership_id,
            role=role,
            status=status,
            expires_at=expires_at,
            attributes=attributes,
            updated_by=updated_by,
        )
        return await self._update_membership_use_case.execute(command)

    async def delete_membership(self, membership_id: uuid.UUID) -> None:
        command = DeleteGroupMembershipCommand(membership_id=membership_id)
        await self._delete_membership_use_case.execute(command)
