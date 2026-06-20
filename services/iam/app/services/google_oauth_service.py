"""Google OIDC federation — authorization redirect, callback, account linking.

Account-linking rule (the one place an account-takeover vector could sneak
in): an *existing* local account is only auto-linked to a Google identity
when the email matches **and** Google reports that email as verified. An
unverified email match never links — it would let anyone who controls an
unverified mailbox claim an existing account just by signing in with
Google. No match at all (by subject or by verified email) provisions a
brand-new, password-less account instead.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.domain.exceptions import (
    GoogleAccountConflictError,
    GoogleTokenVerificationError,
)
from app.infrastructure.db.models.audit_log import AuditLog
from app.infrastructure.db.models.user import User
from app.infrastructure.db.repositories.audit_repo import AuditLogRepository
from app.infrastructure.db.repositories.user_repo import UserRepository
from app.infrastructure.security.google_oidc import GoogleIdentity, GoogleOIDCClient
from app.infrastructure.security.oauth_state_store import OAuthStateStore
from app.services.auth_service import AuthService


class GoogleOAuthService:
    def __init__(
        self,
        session,
        settings: Settings,
        *,
        oidc_client: GoogleOIDCClient,
        state_store: OAuthStateStore,
        auth_service: AuthService,
    ) -> None:
        self._session = session
        self._settings = settings
        self._oidc_client = oidc_client
        self._state_store = state_store
        self._auth_service = auth_service
        self._users = UserRepository(session)
        self._audit_log = AuditLogRepository(session)

    async def start(self) -> str:
        """Returns the URL to redirect the browser to for Google's consent screen."""
        state, nonce = await self._state_store.issue()
        return self._oidc_client.build_authorization_url(state=state, nonce=nonce)

    async def handle_callback(
        self, *, code: str, state: str, ip_address: str | None, user_agent: str | None
    ) -> tuple[str, str, User]:
        nonce = await self._state_store.consume(state)

        token_response = await self._oidc_client.exchange_code(code)
        id_token = token_response.get("id_token")
        if not id_token:
            raise GoogleTokenVerificationError(
                "Google token response did not include an id_token"
            )

        identity = await self._oidc_client.verify_id_token(
            id_token, expected_nonce=nonce
        )
        user, event_type = await self._resolve_user(identity)

        access_token, refresh_token = await self._auth_service.issue_new_session(
            user, ip_address=ip_address, user_agent=user_agent
        )
        await self._audit(
            event_type=event_type,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            context={"google_subject": identity.subject},
        )
        return access_token, refresh_token, user

    async def _resolve_user(self, identity: GoogleIdentity) -> tuple[User, str]:
        existing_by_subject = await self._users.get_by_google_subject(identity.subject)
        if existing_by_subject is not None:
            return existing_by_subject, "auth.google_login.success"

        existing_by_email = await self._users.get_by_email(identity.email)
        if existing_by_email is not None:
            if not identity.email_verified:
                await self._audit(
                    event_type="auth.google_login.link_refused_unverified_email",
                    user_id=existing_by_email.id,
                    ip_address=None,
                    user_agent=None,
                    context={"google_subject": identity.subject},
                )
                raise GoogleTokenVerificationError(
                    "Google has not verified this email — refusing to link it to an "
                    "existing account"
                )
            if (
                existing_by_email.google_subject is not None
                and existing_by_email.google_subject != identity.subject
            ):
                # This email is already linked to a *different* Google
                # account — silently reassigning ownership here would let a
                # second Google account hijack a user it doesn't control.
                raise GoogleAccountConflictError(
                    "This email is already linked to a different Google account"
                )
            existing_by_email.google_subject = identity.subject
            existing_by_email.updated_at = datetime.now(UTC)
            try:
                await self._session.flush()
            except IntegrityError as exc:
                raise GoogleTokenVerificationError(
                    "This Google account is already linked to a different user"
                ) from exc
            return existing_by_email, "auth.google_login.linked"

        now = datetime.now(UTC)
        new_user = User(
            id=uuid.uuid4(),
            email=identity.email,
            full_name=identity.name,
            password_hash=None,
            google_subject=identity.subject,
            attributes={},
            is_active=True,
            is_verified=identity.email_verified,
            is_superuser=False,
            failed_login_count=0,
            created_at=now,
            updated_at=now,
        )
        self._users.add(new_user)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise GoogleTokenVerificationError(
                "This Google account is already linked to a different user"
            ) from exc
        return new_user, "auth.google_login.registered"

    async def _audit(
        self,
        *,
        event_type: str,
        user_id: uuid.UUID,
        ip_address: str | None,
        user_agent: str | None,
        context: dict,
    ) -> None:
        self._audit_log.add(
            AuditLog(
                id=uuid.uuid4(),
                user_id=user_id,
                event_type=event_type,
                ip_address=ip_address,
                user_agent=user_agent,
                context=context,
                created_at=datetime.now(UTC),
            )
        )
        # Commit, not flush — see the matching comment in AuthService._audit:
        # the link-refusal path raises right after this call, and the
        # request-scoped session rolls back on exception.
        await self._session.commit()
