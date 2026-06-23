"""Access governance — access requests, reviews, and approvals (User and
Access APIs Specification).

Deliberately tracked-decision-only: approving or rejecting an AccessRequest
only updates that request's own ``status`` and records an AccessApproval —
it never calls into RoleService/PermissionService to actually grant the
requested role/permission. Applying an approved request is a separate,
deliberate action through the existing role/permission-grant APIs, so an
approval endpoint can never silently mutate a user's real RBAC state.
"""

from __future__ import annotations

import uuid

from app.audit import AuditLogRepository
from app.modules.access_governance.exceptions import (
    AccessApprovalNotFoundError,
    AccessRequestNotFoundError,
    AccessReviewNotFoundError,
)
from app.modules.access_governance.models import AccessApproval, AccessRequest, AccessReview
from app.modules.access_governance.repositories.sqlalchemy.access_approval_repository import (
    AccessApprovalRepository,
)
from app.modules.access_governance.repositories.sqlalchemy.access_request_repository import (
    AccessRequestRepository,
)
from app.modules.access_governance.repositories.sqlalchemy.access_review_repository import (
    AccessReviewRepository,
)
from app.modules.access_governance.schemas.commands.create_access_approval_command import (
    CreateAccessApprovalCommand,
)
from app.modules.access_governance.schemas.commands.create_access_request_command import (
    CreateAccessRequestCommand,
)
from app.modules.access_governance.schemas.commands.create_access_review_command import (
    CreateAccessReviewCommand,
)
from app.modules.access_governance.use_cases.create_access_approval import (
    CreateAccessApprovalUseCase,
)
from app.modules.access_governance.use_cases.create_access_request import (
    CreateAccessRequestUseCase,
)
from app.modules.access_governance.use_cases.create_access_review import (
    CreateAccessReviewUseCase,
)
from app.modules.users.repositories.sqlalchemy.user_repository import UserRepository


class AccessGovernanceService:
    def __init__(self, session) -> None:
        self._session = session
        self._requests = AccessRequestRepository(session)
        self._reviews = AccessReviewRepository(session)
        self._approvals = AccessApprovalRepository(session)
        self._users = UserRepository(session)
        self._audit_log = AuditLogRepository(session)
        self._create_request_use_case = CreateAccessRequestUseCase(
            session, self._requests, self._users, self._audit_log
        )
        self._create_review_use_case = CreateAccessReviewUseCase(
            session, self._reviews, self._audit_log
        )
        self._create_approval_use_case = CreateAccessApprovalUseCase(
            session, self._approvals, self._requests, self._audit_log
        )

    # -- access requests -------------------------------------------------------

    async def create_request(
        self,
        *,
        user_id: uuid.UUID,
        requested_roles: list[str],
        requested_permissions: list[str],
        justification: str | None,
        requested_by: uuid.UUID,
    ) -> AccessRequest:
        command = CreateAccessRequestCommand(
            user_id=user_id,
            requested_roles=requested_roles,
            requested_permissions=requested_permissions,
            justification=justification,
            requested_by=requested_by,
        )
        return await self._create_request_use_case.execute(command)

    async def get_request(self, request_id: uuid.UUID) -> AccessRequest:
        request = await self._requests.get_by_id(request_id)
        if request is None:
            raise AccessRequestNotFoundError(f"No access request with id '{request_id}'")
        return request

    # -- access reviews ---------------------------------------------------------

    async def create_review(
        self,
        *,
        review_scope: str,
        organization_id: uuid.UUID | None,
        review_type: str,
        created_by: uuid.UUID,
    ) -> AccessReview:
        command = CreateAccessReviewCommand(
            review_scope=review_scope,
            organization_id=organization_id,
            review_type=review_type,
            created_by=created_by,
        )
        return await self._create_review_use_case.execute(command)

    async def get_review(self, review_id: uuid.UUID) -> AccessReview:
        review = await self._reviews.get_by_id(review_id)
        if review is None:
            raise AccessReviewNotFoundError(f"No access review with id '{review_id}'")
        return review

    # -- access approvals -------------------------------------------------------

    async def create_approval(
        self,
        *,
        request_id: uuid.UUID,
        decision: str,
        comment: str | None,
        processed_by: uuid.UUID,
    ) -> AccessApproval:
        command = CreateAccessApprovalCommand(
            request_id=request_id,
            decision=decision,
            comment=comment,
            processed_by=processed_by,
        )
        return await self._create_approval_use_case.execute(command)

    async def get_approval(self, approval_id: uuid.UUID) -> AccessApproval:
        approval = await self._approvals.get_by_id(approval_id)
        if approval is None:
            raise AccessApprovalNotFoundError(f"No access approval with id '{approval_id}'")
        return approval
