from __future__ import annotations

from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.core.config import Settings
from app.core.token_blacklist import TokenBlacklist
from app.modules.auth.exceptions import InvalidTokenError
from app.modules.auth.repositories.interfaces.token_repository import RefreshTokenRepository
from app.modules.auth.schemas.commands.logout_command import LogoutCommand
from app.modules.auth.use_cases._audit import record_auth_audit_event
from app.modules.auth.utils.jwt import decode_access_token, decode_refresh_token
from sqlalchemy.ext.asyncio import AsyncSession


class LogoutUseCase:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        token_blacklist: TokenBlacklist,
        refresh_tokens: RefreshTokenRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._session = session
        self._settings = settings
        self._token_blacklist = token_blacklist
        self._refresh_tokens = refresh_tokens
        self._audit_log = audit_log

    async def execute(self, command: LogoutCommand) -> None:
        if command.refresh_token:
            try:
                claims = decode_refresh_token(self._settings, command.refresh_token)
            except InvalidTokenError:
                claims = None
            if claims is not None:
                await self._refresh_tokens.revoke_family(claims.family_id)
                await record_auth_audit_event(
                    self._session, self._audit_log, "auth.logout", claims.subject_id, {}
                )

        if command.access_token:
            try:
                access_claims = decode_access_token(self._settings, command.access_token)
            except InvalidTokenError:
                access_claims = None
            if access_claims is not None:
                ttl_seconds = max(
                    int((access_claims.expires_at - datetime.now(UTC)).total_seconds()),
                    1,
                )
                await self._token_blacklist.add_jti(str(access_claims.jti), ttl_seconds=ttl_seconds)
