from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.access_governance.models import AccessRequest
from app.modules.access_governance.repositories.interfaces.access_request_repository import (
    AccessRequestRepository,
)
from app.modules.access_governance.schemas.commands.create_access_request_command import (
    CreateAccessRequestCommand,
)
from app.modules.access_governance.use_cases._audit import record_audit_event
from app.modules.users.exceptions import UserNotFoundError
from app.modules.users.repositories.sqlalchemy.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession


class CreateAccessRequestUseCase:
    def __init__(
        self,
        session: AsyncSession,
        requests: AccessRequestRepository,
        users: UserRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._session = session
        self._requests = requests
        self._users = users
        self._audit_log = audit_log

    async def execute(self, command: CreateAccessRequestCommand) -> AccessRequest:
        if await self._users.get_by_id(command.user_id) is None:
            raise UserNotFoundError(f"No user with id '{command.user_id}'")

        now = datetime.now(UTC)
        request = AccessRequest(
            id=uuid.uuid4(),
            user_id=command.user_id,
            requested_by=command.requested_by,
            requested_roles=command.requested_roles,
            requested_permissions=command.requested_permissions,
            justification=command.justification,
            status="PENDING_APPROVAL",
            created_at=now,
            updated_at=now,
        )
        self._requests.add(request)
        await self._session.flush()

        await record_audit_event(
            self._session,
            self._audit_log,
            "access.request.created",
            command.requested_by,
            {
                "access_request_id": str(request.id),
                "user_id": str(command.user_id),
                "requested_roles": command.requested_roles,
                "requested_permissions": command.requested_permissions,
            },
        )
        return request
