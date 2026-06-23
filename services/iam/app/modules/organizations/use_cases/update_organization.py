from __future__ import annotations

from datetime import UTC, datetime

from app.modules.organizations.exceptions import OrganizationNotFoundError
from app.modules.organizations.models import Organization
from app.modules.organizations.repositories.interfaces.organization_repository import (
    OrganizationRepository,
)
from app.modules.organizations.schemas.commands.update_organization_command import (
    UpdateOrganizationCommand,
)
from sqlalchemy.ext.asyncio import AsyncSession


class UpdateOrganizationUseCase:
    def __init__(self, session: AsyncSession, orgs: OrganizationRepository) -> None:
        self._session = session
        self._orgs = orgs

    async def execute(self, command: UpdateOrganizationCommand) -> Organization:
        org = await self._orgs.get_by_id(command.organization_id)
        if org is None:
            raise OrganizationNotFoundError(f"No organization with id '{command.organization_id}'")

        if command.name is not None:
            org.name = command.name
        if command.description is not None:
            org.description = command.description
        if command.default_attributes is not None:
            org.default_attributes = command.default_attributes
        if command.is_reserved is not None:
            org.is_reserved = command.is_reserved
        org.updated_at = datetime.now(UTC)
        await self._session.commit()
        return org
