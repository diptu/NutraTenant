from __future__ import annotations

from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.policies.exceptions import PolicyNotFoundError
from app.modules.policies.models import Policy
from app.modules.policies.repositories.interfaces.policy_repository import PolicyRepository
from app.modules.policies.schemas.commands.publish_policy_command import PublishPolicyCommand
from app.modules.policies.use_cases._audit import record_policy_audit_event
from sqlalchemy.ext.asyncio import AsyncSession


class PublishPolicyUseCase:
    def __init__(
        self, session: AsyncSession, policies: PolicyRepository, audit_log: AuditLogRepository
    ) -> None:
        self._session = session
        self._policies = policies
        self._audit_log = audit_log

    async def execute(self, command: PublishPolicyCommand) -> Policy:
        policy = await self._policies.get_by_id(command.policy_id)
        if policy is None:
            raise PolicyNotFoundError(f"No policy with id '{command.policy_id}'")

        policy.status = "PUBLISHED"
        policy.version += 1
        policy.updated_at = datetime.now(UTC)
        await self._session.commit()

        await record_policy_audit_event(
            self._session,
            self._audit_log,
            "abac.policy.published",
            command.actor_id,
            policy,
            {"new_version": policy.version, "comment": command.comment},
        )
        return policy
