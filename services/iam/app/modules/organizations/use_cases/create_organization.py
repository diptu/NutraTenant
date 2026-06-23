from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.infrastructure.database.associations import UserOrganizationRole
from app.modules.organizations.exceptions import OrganizationAlreadyExistsError
from app.modules.organizations.models import Organization
from app.modules.organizations.repositories.interfaces.organization_repository import (
    OrganizationRepository,
)
from app.modules.organizations.schemas.commands.create_organization_command import (
    CreateOrganizationCommand,
)
from app.modules.reserved_tenant_ids.exceptions import ReservedTenantIdError
from app.modules.reserved_tenant_ids.repositories.interfaces.reserved_tenant_id_repository import (
    ReservedTenantIdRepository,
)
from app.modules.roles.repositories.interfaces.role_repository import RoleRepository
from app.modules.roles.service import DEFAULT_ORG_ROLES, provision_role
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class CreateOrganizationUseCase:
    def __init__(
        self,
        session: AsyncSession,
        orgs: OrganizationRepository,
        roles: RoleRepository,
        reserved_tenant_ids: ReservedTenantIdRepository,
    ) -> None:
        self._session = session
        self._orgs = orgs
        self._roles = roles
        self._reserved_tenant_ids = reserved_tenant_ids

    async def execute(self, command: CreateOrganizationCommand) -> Organization:
        if await self._reserved_tenant_ids.get_by_tenant_id(command.slug) is not None:
            raise ReservedTenantIdError(f"tenant_id '{command.slug}' is reserved and cannot be used")
        if await self._orgs.get_by_slug(command.slug) is not None:
            raise OrganizationAlreadyExistsError(f"Organization slug '{command.slug}' is already taken")

        now = datetime.now(UTC)
        org = Organization(
            id=uuid.uuid4(),
            name=command.name,
            slug=command.slug,
            description=command.description,
            owner_id=command.owner_id,
            is_active=True,
            default_attributes={},
            created_at=now,
            updated_at=now,
        )
        self._orgs.add(org)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise OrganizationAlreadyExistsError(
                f"Organization slug '{command.slug}' is already taken"
            ) from exc

        roles = {
            code: await provision_role(self._session, self._roles, org.id, code=code, name=name)
            for code, name in DEFAULT_ORG_ROLES
        }

        membership = UserOrganizationRole(
            id=uuid.uuid4(),
            organization_id=org.id,
            user_id=command.owner_id,
            role_id=roles["owner"].id,
            invited_by=None,
            is_active=True,
            joined_at=now,
            created_at=now,
            updated_at=now,
        )
        self._orgs.add_membership(membership)
        await self._session.commit()
        return org
