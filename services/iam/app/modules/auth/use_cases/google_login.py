from __future__ import annotations

from app.modules.auth.utils.oauth import GoogleOIDCClient, OAuthStateStore


class GoogleLoginUseCase:
    def __init__(self, oidc_client: GoogleOIDCClient, state_store: OAuthStateStore) -> None:
        self._oidc_client = oidc_client
        self._state_store = state_store

    async def execute(self) -> str:
        """Returns the URL to redirect the browser to for Google's consent screen."""
        state, nonce = await self._state_store.issue()
        return self._oidc_client.build_authorization_url(state=state, nonce=nonce)
