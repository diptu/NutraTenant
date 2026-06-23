"""Google OIDC federation — authorization redirect, callback, account linking.

See app.modules.auth.use_cases.google_callback for the account-linking rule
(the one place an account-takeover vector could sneak in).
"""

from __future__ import annotations

from app.audit import AuditLogRepository
from app.core.config import Settings
from app.modules.auth.schemas.commands.google_callback_command import GoogleCallbackCommand
from app.modules.auth.service import AuthService
from app.modules.auth.use_cases.google_callback import GoogleCallbackUseCase
from app.modules.auth.use_cases.google_login import GoogleLoginUseCase
from app.modules.auth.utils.oauth import GoogleOIDCClient, OAuthStateStore
from app.modules.users.models import User
from app.modules.users.repositories.sqlalchemy.user_repository import UserRepository
from app.shared.utils.base_service import BaseService

__all__ = ["GoogleOAuthService"]


class GoogleOAuthService(BaseService):
    def __init__(
        self,
        session,
        settings: Settings,
        *,
        oidc_client: GoogleOIDCClient,
        state_store: OAuthStateStore,
        auth_service: AuthService,
    ) -> None:
        super().__init__(session)
        self._settings = settings
        self._oidc_client = oidc_client
        self._state_store = state_store
        self._auth_service = auth_service
        self._users = UserRepository(session)
        self._audit_log = AuditLogRepository(session)
        self._login_use_case = GoogleLoginUseCase(oidc_client, state_store)
        self._callback_use_case = GoogleCallbackUseCase(
            session, oidc_client, state_store, auth_service, self._users, self._audit_log
        )

    async def start(self) -> str:
        """Returns the URL to redirect the browser to for Google's consent screen."""
        return await self._login_use_case.execute()

    async def handle_callback(
        self, *, code: str, state: str, ip_address: str | None, user_agent: str | None
    ) -> tuple[str, str, User]:
        command = GoogleCallbackCommand(
            code=code, state=state, ip_address=ip_address, user_agent=user_agent
        )
        return await self._callback_use_case.execute(command)
