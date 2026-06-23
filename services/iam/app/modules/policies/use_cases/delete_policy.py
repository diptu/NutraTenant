from __future__ import annotations

from app.audit import AuditLogRepository
from app.modules.policies.exceptions import PolicyNotFoundError
from app.modules.policies.repositories.interfaces.policy_repository import PolicyRepository
from app.modules.policies.schemas.commands.delete_policy_command import DeletePolicyCommand
from app.modules.policies.use_cases._audit import record_policy_audit_event
from sqlalchemy.ext.asyncio import AsyncSession


class DeletePolicyUseCase:
    def __init__(
        self, session: AsyncSession, policies: PolicyRepository, audit_log: AuditLogRepository
    ) -> None:
        self._session = session
        self._policies = policies
        self._audit_log = audit_log

    async def execute(self, command: DeletePolicyCommand) -> None:
        policy = await self._policies.get_by_id(command.policy_id)
        if policy is None:
            raise PolicyNotFoundError(f"No policy with id '{command.policy_id}'")
        await self._policies.delete(policy)
        await record_policy_audit_event(
            self._session, self._audit_log, "abac.policy.deleted", command.actor_id, policy, {}
        )
