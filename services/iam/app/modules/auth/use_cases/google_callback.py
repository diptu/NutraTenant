"""Account-linking rule (the one place an account-takeover vector could
sneak in): an *existing* local account is only auto-linked to a Google
identity when the email matches **and** Google reports that email as
verified. An unverified email match never links — it would let anyone
who controls an unverified mailbox claim an existing account just by
signing in with Google. No match at all (by subject or by verified
email) provisions a brand-new, password-less account instead."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.audit import AuditLogRepository
from app.modules.auth.exceptions import GoogleAccountConflictError, GoogleTokenVerificationError
from app.modules.auth.schemas.commands.google_callback_command import GoogleCallbackCommand
from app.modules.auth.service import AuthService
from app.modules.auth.use_cases._audit import record_auth_audit_event
from app.modules.auth.utils.oauth import GoogleIdentity, GoogleOIDCClient, OAuthStateStore
from app.modules.users.models import User
from app.modules.users.repositories.interfaces.user_repository import UserRepository
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class GoogleCallbackUseCase:
    def __init__(
        self,
        session: AsyncSession,
        oidc_client: GoogleOIDCClient,
        state_store: OAuthStateStore,
        auth_service: AuthService,
        users: UserRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._session = session
        self._oidc_client = oidc_client
        self._state_store = state_store
        self._auth_service = auth_service
        self._users = users
        self._audit_log = audit_log

    async def execute(self, command: GoogleCallbackCommand) -> tuple[str, str, User]:
        nonce = await self._state_store.consume(command.state)

        token_response = await self._oidc_client.exchange_code(command.code)
        id_token = token_response.get("id_token")
        if not id_token:
            raise GoogleTokenVerificationError("Google token response did not include an id_token")

        identity = await self._oidc_client.verify_id_token(id_token, expected_nonce=nonce)
        user, event_type = await self._resolve_user(identity)

        token_pair = await self._auth_service.issue_new_session(
            user, ip_address=command.ip_address, user_agent=command.user_agent
        )
        await record_auth_audit_event(
            self._session,
            self._audit_log,
            event_type,
            user.id,
            {"google_subject": identity.subject},
            ip_address=command.ip_address,
            user_agent=command.user_agent,
        )
        return token_pair.access_token, token_pair.refresh_token, user

    async def _resolve_user(self, identity: GoogleIdentity) -> tuple[User, str]:
        existing_by_subject = await self._users.get_by_google_subject(identity.subject)
        if existing_by_subject is not None:
            return existing_by_subject, "auth.google_login.success"

        existing_by_email = await self._users.get_by_email(identity.email)
        if existing_by_email is not None:
            if not identity.email_verified:
                await record_auth_audit_event(
                    self._session,
                    self._audit_log,
                    "auth.google_login.link_refused_unverified_email",
                    existing_by_email.id,
                    {"google_subject": identity.subject},
                )
                raise GoogleTokenVerificationError(
                    "Google has not verified this email — refusing to link it to an existing account"
                )
            if (
                existing_by_email.google_subject is not None
                and existing_by_email.google_subject != identity.subject
            ):
                # This email is already linked to a *different* Google
                # account — silently reassigning ownership here would let a
                # second Google account hijack a user it doesn't control.
                raise GoogleAccountConflictError("This email is already linked to a different Google account")
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
