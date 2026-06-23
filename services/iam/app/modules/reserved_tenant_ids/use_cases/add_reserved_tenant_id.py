from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.modules.reserved_tenant_ids.exceptions import ReservedTenantIdAlreadyExistsError
from app.modules.reserved_tenant_ids.models import ReservedTenantId
from app.modules.reserved_tenant_ids.repositories.interfaces.reserved_tenant_id_repository import (
    ReservedTenantIdRepository,
)
from app.modules.reserved_tenant_ids.schemas.commands.add_reserved_tenant_id_command import (
    AddReservedTenantIdCommand,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class AddReservedTenantIdUseCase:
    def __init__(self, session: AsyncSession, reserved: ReservedTenantIdRepository) -> None:
        self._session = session
        self._reserved = reserved

    async def execute(self, command: AddReservedTenantIdCommand) -> ReservedTenantId:
        if await self._reserved.get_by_tenant_id(command.tenant_id) is not None:
            raise ReservedTenantIdAlreadyExistsError(
                f"tenant_id '{command.tenant_id}' is already reserved"
            )

        entry = ReservedTenantId(
            id=uuid.uuid4(),
            tenant_id=command.tenant_id,
            reason=command.reason,
            created_by=command.created_by,
            created_at=datetime.now(UTC),
        )
        self._reserved.add(entry)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ReservedTenantIdAlreadyExistsError(
                f"tenant_id '{command.tenant_id}' is already reserved"
            ) from exc
        return entry
