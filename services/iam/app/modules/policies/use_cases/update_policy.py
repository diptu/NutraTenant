from __future__ import annotations

from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.policies.exceptions import PolicyNotFoundError
from app.modules.policies.models import Policy
from app.modules.policies.repositories.interfaces.policy_repository import PolicyRepository
from app.modules.policies.schemas.commands.update_policy_command import UpdatePolicyCommand
from app.modules.policies.use_cases._audit import record_policy_audit_event
from app.modules.policies.use_cases._conditions import (
    normalize_and_validate_conditions,
    validate_effect,
)
from sqlalchemy.ext.asyncio import AsyncSession


class UpdatePolicyUseCase:
    def __init__(
        self, session: AsyncSession, policies: PolicyRepository, audit_log: AuditLogRepository
    ) -> None:
        self._session = session
        self._policies = policies
        self._audit_log = audit_log

    async def execute(self, command: UpdatePolicyCommand) -> Policy:
        """``conditions=None`` is ambiguous between "leave unchanged" and
        "clear it" — ``update_conditions`` disambiguates; the route layer sets
        it from Pydantic's "was this field actually present in the request body"
        tracking rather than from the value itself."""
        policy = await self._policies.get_by_id(command.policy_id)
        if policy is None:
            raise PolicyNotFoundError(f"No policy with id '{command.policy_id}'")

        if command.display_name is not None:
            policy.display_name = command.display_name
        if command.description is not None:
            policy.description = command.description
        if command.type is not None:
            policy.type = command.type
        if command.status is not None:
            policy.status = command.status
        if command.effect is not None:
            validate_effect(command.effect)
            policy.effect = command.effect
        if command.priority is not None:
            policy.priority = command.priority
        if command.resource_types is not None:
            policy.resource_types = command.resource_types
        if command.actions is not None:
            policy.actions = command.actions
        if command.subjects is not None:
            policy.subjects = command.subjects
        if command.update_conditions:
            policy.conditions = normalize_and_validate_conditions(command.conditions)
        if command.metadata is not None:
            policy.extra_metadata = command.metadata

        policy.version += 1
        policy.updated_at = datetime.now(UTC)
        await self._session.commit()

        await record_policy_audit_event(
            self._session,
            self._audit_log,
            "abac.policy.updated",
            command.actor_id,
            policy,
            {"new_version": policy.version},
        )
        return policy
