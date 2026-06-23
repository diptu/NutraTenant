"""Auth-domain errors — login, registration, MFA, refresh rotation, Google
federation. Translated to HTTP in app/main.py."""

from __future__ import annotations

from app.shared.exceptions.base import AlreadyExistsError, DomainError


class EmailAlreadyExistsError(AlreadyExistsError):
    """Registration attempted with an email already in use."""


class UsernameAlreadyExistsError(AlreadyExistsError):
    """A user create/update attempted with a username already in use."""


class MfaAlreadyEnabledError(AlreadyExistsError):
    """MFA setup/confirm was attempted on an account that already has it enabled."""


class GoogleAccountConflictError(AlreadyExistsError):
    """This email is already linked to a *different* Google account — refuse to
    silently reassign which Google identity owns a local user."""


class InvalidCredentialsError(DomainError):
    """Login attempted with a wrong email/password combination."""


class InvalidTokenError(DomainError):
    """A JWT/refresh/reset token failed signature, claim, or lookup validation."""


class InvalidMfaCodeError(DomainError):
    """A TOTP code or recovery code failed verification — distinct from
    ``InvalidTokenError`` since no token is involved, just a wrong/expired
    one-time code; gets its own audit event type at the call site."""


class AccountLockedError(DomainError):
    """Login blocked by the brute-force lockout policy."""

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Account locked. Retry after {retry_after_seconds} seconds.")


class RateLimitExceededError(DomainError):
    """Too many requests for this key (e.g. email) within the current window — 429."""

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Rate limit exceeded. Retry after {retry_after_seconds} seconds.")


class TenantSelectionRequiredError(DomainError):
    """Login succeeded but the user belongs to more than one organization and
    no ``tenant_id`` was given to disambiguate — 409, carrying the list of
    organizations the caller can retry the login with."""

    def __init__(self, organizations: list[dict]) -> None:
        self.organizations = organizations
        super().__init__("Multiple tenants available for this account; specify tenant_id to continue")


class SessionNotFoundError(DomainError):
    """No active session with this id belongs to this user — covers
    unknown/malformed session ids, someone else's session, and an already
    revoked/expired one alike (no signal is leaked about which)."""


class MfaNotEnabledError(DomainError):
    """MFA confirm/disable/login-verify was attempted without an active
    (or pending) enrollment to act on."""


class RefreshTokenReusedError(InvalidTokenError):
    """A refresh token already consumed by a prior rotation was replayed.

    Surfaces to the client identically to any other invalid refresh token
    (still a 401 via the ``InvalidTokenError`` mapping) — the distinction
    only matters internally, where it triggers revoking the whole rotation
    family and a higher-severity audit event, since replay is a strong
    signal of token theft rather than an expired/garbage token.
    """


class OAuthStateError(InvalidTokenError):
    """The ``state`` or ``nonce`` returned by the OIDC provider didn't match
    what this service issued — treated as a forged/replayed callback."""


class GoogleConsentDeniedError(DomainError):
    """Google redirected back with an ``error`` query param (e.g. the user
    clicked "Cancel" on the consent screen) instead of an authorization
    code — a client-side outcome, not a token/credential failure, so it
    maps to 400 rather than 401."""


class GoogleTokenVerificationError(InvalidTokenError):
    """Google's ID token failed signature, issuer, audience, or claim validation."""
