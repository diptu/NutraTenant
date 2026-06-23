from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.policies.exceptions import PolicyAlreadyExistsError
from app.modules.policies.models import Policy
from app.modules.policies.repositories.interfaces.policy_repository import PolicyRepository
from app.modules.policies.schemas.commands.create_policy_command import CreatePolicyCommand
from app.modules.policies.use_cases._audit import record_policy_audit_event
from app.modules.policies.use_cases._conditions import (
    normalize_and_validate_conditions,
    validate_effect,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class CreatePolicyUseCase:
    def __init__(
        self, session: AsyncSession, policies: PolicyRepository, audit_log: AuditLogRepository
    ) -> None:
        self._session = session
        self._policies = policies
        self._audit_log = audit_log

    async def execute(self, command: CreatePolicyCommand) -> Policy:
        validate_effect(command.effect)
        normalized_conditions = normalize_and_validate_conditions(command.conditions)

        if await self._policies.get_by_name(command.name) is not None:
            raise PolicyAlreadyExistsError(f"A policy named '{command.name}' already exists")

        now = datetime.now(UTC)
        policy = Policy(
            id=uuid.uuid4(),
            name=command.name,
            display_name=command.display_name,
            description=command.description,
            type=command.type,
            status=command.status,
            effect=command.effect,
            priority=command.priority,
            organization_id=command.organization_id,
            resource_types=command.resource_types,
            actions=command.actions,
            subjects=command.subjects,
            conditions=normalized_conditions,
            extra_metadata=command.metadata,
            version=1,
            created_at=now,
            updated_at=now,
            created_by=command.created_by,
        )
        self._policies.add(policy)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise PolicyAlreadyExistsError(f"A policy named '{command.name}' already exists") from exc

        await record_policy_audit_event(
            self._session,
            self._audit_log,
            "abac.policy.created",
            command.created_by,
            policy,
            {
                "effect": command.effect,
                "resource_types": command.resource_types,
                "actions": command.actions,
            },
        )
        return policy
