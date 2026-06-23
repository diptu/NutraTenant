from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.access_governance.exceptions import (
    AccessRequestAlreadyDecidedError,
    AccessRequestNotFoundError,
)
from app.modules.access_governance.models import AccessApproval
from app.modules.access_governance.repositories.interfaces.access_approval_repository import (
    AccessApprovalRepository,
)
from app.modules.access_governance.repositories.interfaces.access_request_repository import (
    AccessRequestRepository,
)
from app.modules.access_governance.schemas.commands.create_access_approval_command import (
    CreateAccessApprovalCommand,
)
from app.modules.access_governance.use_cases._audit import record_audit_event
from sqlalchemy.ext.asyncio import AsyncSession


class CreateAccessApprovalUseCase:
    def __init__(
        self,
        session: AsyncSession,
        approvals: AccessApprovalRepository,
        requests: AccessRequestRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._session = session
        self._approvals = approvals
        self._requests = requests
        self._audit_log = audit_log

    async def execute(self, command: CreateAccessApprovalCommand) -> AccessApproval:
        request = await self._requests.get_by_id(command.request_id)
        if request is None:
            raise AccessRequestNotFoundError(f"No access request with id '{command.request_id}'")
        if request.status != "PENDING_APPROVAL":
            raise AccessRequestAlreadyDecidedError(
                f"Access request '{command.request_id}' was already decided ('{request.status}')"
            )

        now = datetime.now(UTC)
        approval = AccessApproval(
            id=uuid.uuid4(),
            access_request_id=command.request_id,
            decision=command.decision,
            comment=command.comment,
            status="COMPLETED",
            processed_by=command.processed_by,
            processed_at=now,
            created_at=now,
        )
        self._approvals.add(approval)

        request.status = command.decision
        request.updated_at = now

        await self._session.flush()
        await record_audit_event(
            self._session,
            self._audit_log,
            "access.request.decided",
            command.processed_by,
            {
                "access_request_id": str(command.request_id),
                "access_approval_id": str(approval.id),
                "decision": command.decision,
            },
        )
        return approval
