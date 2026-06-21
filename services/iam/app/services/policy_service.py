"""ABAC policy CRUD — the "Fine-Grained Layer" management surface.

Validates ``conditions`` structurally at write time (see
app/domain/policy_conditions.py) so a malformed rule is rejected here, not
discovered mid-evaluation by the PDP for some unrelated request.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.domain.exceptions import (
    InvalidPolicyConditionsError,
    PolicyAlreadyExistsError,
    PolicyNotFoundError,
)
from app.domain.policy_conditions import ConditionError, validate_condition_schema
from app.infrastructure.db.models.audit_log import AuditLog
from app.infrastructure.db.models.policy import Policy
from app.infrastructure.db.repositories.audit_repo import AuditLogRepository
from app.infrastructure.db.repositories.policy_repo import PolicyRepository
from sqlalchemy.exc import IntegrityError

_VALID_EFFECTS = ("allow", "deny")


class PolicyService:
    def __init__(self, session) -> None:
        self._session = session
        self._policies = PolicyRepository(session)
        self._audit_log = AuditLogRepository(session)

    async def list_policies(self) -> list[Policy]:
        return await self._policies.list_all(limit=500)

    async def get_policy(self, policy_id: uuid.UUID) -> Policy:
        policy = await self._policies.get_by_id(policy_id)
        if policy is None:
            raise PolicyNotFoundError(f"No policy with id '{policy_id}'")
        return policy

    async def create_policy(
        self,
        *,
        name: str,
        description: str | None,
        effect: str,
        resource: str,
        action: str,
        conditions: dict | None,
        created_by: uuid.UUID,
    ) -> Policy:
        self._validate_effect(effect)
        self._validate_conditions(conditions)

        if await self._policies.get_by_name(name) is not None:
            raise PolicyAlreadyExistsError(f"A policy named '{name}' already exists")

        now = datetime.now(UTC)
        policy = Policy(
            id=uuid.uuid4(),
            name=name,
            description=description,
            effect=effect,
            resource=resource,
            action=action,
            conditions=conditions,
            version=1,
            is_active=True,
            created_at=now,
            updated_at=now,
            created_by=created_by,
        )
        self._policies.add(policy)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise PolicyAlreadyExistsError(f"A policy named '{name}' already exists") from exc

        await self._audit(
            event_type="abac.policy.created",
            actor_id=created_by,
            policy=policy,
            extra={"effect": effect, "resource": resource, "action": action},
        )
        return policy

    async def update_policy(
        self,
        policy_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        description: str | None = None,
        effect: str | None = None,
        conditions: dict | None = None,
        update_conditions: bool = False,
        is_active: bool | None = None,
    ) -> Policy:
        """``conditions=None`` is ambiguous between "leave unchanged" and
        "clear it" — ``update_conditions`` disambiguates; the route layer sets
        it from Pydantic's "was this field actually present in the request body"
        tracking rather than from the value itself."""
        policy = await self.get_policy(policy_id)

        if description is not None:
            policy.description = description
        if effect is not None:
            self._validate_effect(effect)
            policy.effect = effect
        if update_conditions:
            self._validate_conditions(conditions)
            policy.conditions = conditions
        if is_active is not None:
            policy.is_active = is_active

        policy.version += 1
        policy.updated_at = datetime.now(UTC)
        await self._session.commit()

        await self._audit(
            event_type="abac.policy.updated",
            actor_id=actor_id,
            policy=policy,
            extra={"new_version": policy.version},
        )
        return policy

    async def delete_policy(self, policy_id: uuid.UUID, *, actor_id: uuid.UUID) -> None:
        policy = await self.get_policy(policy_id)
        await self._policies.delete(policy)
        await self._audit(
            event_type="abac.policy.deleted",
            actor_id=actor_id,
            policy=policy,
            extra={},
        )

    def _validate_effect(self, effect: str) -> None:
        if effect not in _VALID_EFFECTS:
            raise InvalidPolicyConditionsError(f"effect must be one of {_VALID_EFFECTS}, got '{effect}'")

    def _validate_conditions(self, conditions: dict | None) -> None:
        try:
            validate_condition_schema(conditions)
        except ConditionError as exc:
            raise InvalidPolicyConditionsError(str(exc)) from exc

    async def _audit(self, *, event_type: str, actor_id: uuid.UUID, policy: Policy, extra: dict) -> None:
        self._audit_log.add(
            AuditLog(
                id=uuid.uuid4(),
                user_id=actor_id,
                event_type=event_type,
                context={
                    "policy_id": str(policy.id),
                    "policy_name": policy.name,
                    **extra,
                },
                created_at=datetime.now(UTC),
            )
        )
        await self._session.commit()
