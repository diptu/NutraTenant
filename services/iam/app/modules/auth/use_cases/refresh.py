from __future__ import annotations

from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.core.config import Settings
from app.modules.auth.exceptions import InvalidTokenError, RefreshTokenReusedError
from app.modules.auth.repositories.interfaces.token_repository import RefreshTokenRepository
from app.modules.auth.schemas.commands.refresh_command import RefreshCommand
from app.modules.auth.schemas.dto.token_pair_dto import TokenPair
from app.modules.auth.use_cases._audit import record_auth_audit_event
from app.modules.auth.use_cases._dates import aware
from app.modules.auth.use_cases._session import issue_token_pair
from app.modules.auth.utils.jwt import decode_refresh_token
from app.modules.organizations.models import Organization
from app.modules.organizations.repositories.interfaces.organization_repository import (
    OrganizationRepository,
)
from app.modules.users.exceptions import UserNotFoundError
from app.modules.users.models import User
from sqlalchemy.ext.asyncio import AsyncSession


class RefreshUseCase:
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

    async def execute(self, command: RefreshCommand) -> TokenPair:
        claims = decode_refresh_token(self._settings, command.refresh_token)
        stored = await self._refresh_tokens.get_by_id(claims.jti)

        if stored is None:
            raise InvalidTokenError("Unknown refresh token")

        if stored.revoked_at is not None:
            await self._refresh_tokens.revoke_family(stored.family_id)
            await record_auth_audit_event(
                self._session,
                self._audit_log,
                "auth.refresh.reuse_detected",
                stored.user_id,
                {"family_id": str(stored.family_id)},
                ip_address=command.ip_address,
                user_agent=command.user_agent,
            )
            raise RefreshTokenReusedError("Refresh token has already been used")

        if aware(stored.expires_at) < datetime.now(UTC):
            raise InvalidTokenError("Refresh token has expired")

        user = await self._session.get(User, stored.user_id)
        if user is None or not user.is_active:
            raise UserNotFoundError("Refresh token's user is no longer valid")

        # Re-resolve the tenant fresh from the DB on every rotation rather
        # than trusting a stale prior claim — keeps the new row's
        # organization_id (and thus what get_current_tenant_slug resolves)
        # from going stale if membership changed since the last rotation.
        # Membership having been revoked since just drops tenant context,
        # same as in VerifyMfaAndLoginUseCase, rather than failing the
        # refresh outright.
        organization: Organization | None = None
        if stored.organization_id is not None:
            organization = await self._orgs.get_by_id(stored.organization_id)
            if organization is not None:
                membership = await self._orgs.get_membership(stored.organization_id, user.id)
                organization = organization if membership is not None else None

        token_pair = await issue_token_pair(
            self._session,
            self._settings,
            self._refresh_tokens,
            user,
            family_id=stored.family_id,
            ip_address=command.ip_address,
            user_agent=command.user_agent,
            rotates=stored,
            organization=organization,
        )
        await record_auth_audit_event(
            self._session,
            self._audit_log,
            "auth.refresh.rotated",
            user.id,
            {"family_id": str(stored.family_id)},
            ip_address=command.ip_address,
            user_agent=command.user_agent,
        )
        return token_pair
