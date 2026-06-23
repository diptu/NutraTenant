from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.organizations.models import Organization
    from app.modules.roles.models import Role
    from app.modules.users.models import User


@dataclass(frozen=True, slots=True)
class LoginResult:
    """Either a completed login (``access_token``/``refresh_token`` set) or
    an MFA challenge (``mfa_challenge_token`` set) the caller must redeem via
    ``VerifyMfaAndLoginUseCase`` before getting real tokens.

    ``organization``/``role``/``permissions`` describe the tenant context the
    session was bound to (see ``AuthService._resolve_tenant``) — all empty
    when the account belongs to no organization. ``previous_last_login_at``
    is the user's last-login timestamp *before* this one, for display only.
    """

    user: User
    mfa_required: bool
    access_token: str | None = None
    refresh_token: str | None = None
    mfa_challenge_token: str | None = None
    organization: Organization | None = None
    role: Role | None = None
    permissions: list[str] = field(default_factory=list)
    session_id: uuid.UUID | None = None
    session_issued_at: datetime | None = None
    session_expires_at: datetime | None = None
    previous_last_login_at: datetime | None = None
