from __future__ import annotations

import uuid

from app.audit import AuditLogRepository
from app.core.config import Settings
from app.modules.auth.exceptions import InvalidTokenError
from app.modules.auth.models import RefreshToken
from app.modules.auth.repositories.interfaces.token_repository import RefreshTokenRepository
from app.modules.auth.schemas.commands.switch_tenant_command import SwitchTenantCommand
from app.modules.auth.schemas.dto.switch_tenant_result_dto import SwitchTenantResult
from app.modules.auth.use_cases._audit import record_auth_audit_event
from app.modules.auth.use_cases._session import issue_token_pair
from app.modules.auth.utils.jwt import decode_refresh_token
from app.modules.organizations.exceptions import OrganizationNotFoundError
from app.modules.organizations.repositories.interfaces.organization_repository import (
    OrganizationRepository,
)
from app.shared.exceptions.base import ForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession


class SwitchTenantUseCase:
    """Re-mints the caller's access token under a *different* tenant
    they already have an active membership in — no re-authentication.

    Rotates ``current_refresh_token`` into the new tenant context (if
    it's still a live, unrevoked token belonging to this user) via the
    same rotation machinery as a normal /refresh — without this, a later
    silent token refresh would re-resolve the *old*
    ``stored.organization_id`` and silently revert the switch. A caller
    with no usable refresh token on hand instead gets a brand-new
    session (its own family) under the new tenant — every access token
    must point at *some* session row, since org/role context is resolved
    from it dynamically rather than embedded directly (see
    app.modules.auth.dependencies.get_current_tenant_slug); there's no
    "standalone" access token without one.
    """

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        orgs: OrganizationRepository,
        refresh_tokens: RefreshTokenRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._session = session
        self._settings = settings
        self._orgs = orgs
        self._refresh_tokens = refresh_tokens
        self._audit_log = audit_log

    async def execute(self, command: SwitchTenantCommand) -> SwitchTenantResult:
        organization = await self._orgs.get_by_slug(command.tenant_slug)
        if organization is None:
            raise OrganizationNotFoundError(f"No tenant '{command.tenant_slug}'")

        membership = await self._orgs.get_membership(organization.id, command.user.id)
        if membership is None or not membership.is_active:
            raise ForbiddenError("You are not an active member of this tenant")

        stored: RefreshToken | None = None
        if command.current_refresh_token is not None:
            try:
                refresh_claims = decode_refresh_token(self._settings, command.current_refresh_token)
            except InvalidTokenError:
                refresh_claims = None
            if refresh_claims is not None and refresh_claims.subject_id == command.user.id:
                candidate = await self._refresh_tokens.get_by_id(refresh_claims.jti)
                if candidate is not None and candidate.revoked_at is None:
                    stored = candidate

        token_pair = await issue_token_pair(
            self._session,
            self._settings,
            self._refresh_tokens,
            command.user,
            family_id=stored.family_id if stored is not None else uuid.uuid4(),
            ip_address=command.ip_address,
            user_agent=command.user_agent,
            rotates=stored,
            organization=organization,
        )
        access_token = token_pair.access_token
        refresh_token_out: str | None = token_pair.refresh_token

        await record_auth_audit_event(
            self._session,
            self._audit_log,
            "auth.tenant_switched",
            command.user.id,
            {"organization_id": str(organization.id)},
            ip_address=command.ip_address,
            user_agent=command.user_agent,
        )
        return SwitchTenantResult(
            access_token=access_token,
            refresh_token=refresh_token_out,
            organization=organization,
            role=membership.role,
        )
