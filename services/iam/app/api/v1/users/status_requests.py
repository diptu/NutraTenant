"""Request bodies for GET/PATCH /api/v1/user-status/{user_id}
(User Domain API Specification) — a thin facade over the same lifecycle
``status`` column PATCH /users/{user_id}/status already manages.

Reuses the existing (six-value) ``UserStatus`` literal rather than the
spec's own five-value "Allowed" list (which omits PENDING_VERIFICATION) —
rejecting that one value here, while PATCH /users/{user_id}/status accepts
it for the same column, would be an arbitrary inconsistency between two
endpoints managing identical state.
"""

from __future__ import annotations

from app.modules.users.models import UserStatus
from pydantic import BaseModel


class UpdateUserStatusRequest(BaseModel):
    status: UserStatus
