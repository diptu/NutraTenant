from __future__ import annotations

from app.modules.reserved_tenant_ids.exceptions import ReservedTenantIdNotFoundError
from app.modules.reserved_tenant_ids.repositories.interfaces.reserved_tenant_id_repository import (
    ReservedTenantIdRepository,
)
from app.modules.reserved_tenant_ids.schemas.commands.remove_reserved_tenant_id_command import (
    RemoveReservedTenantIdCommand,
)
from sqlalchemy.ext.asyncio import AsyncSession


class RemoveReservedTenantIdUseCase:
    def __init__(self, session: AsyncSession, reserved: ReservedTenantIdRepository) -> None:
        self._session = session
        self._reserved = reserved

    async def execute(self, command: RemoveReservedTenantIdCommand) -> None:
        entry = await self._reserved.get_by_tenant_id(command.tenant_id)
        if entry is None:
            raise ReservedTenantIdNotFoundError(f"tenant_id '{command.tenant_id}' is not reserved")
        await self._reserved.delete(entry)
        await self._session.commit()
