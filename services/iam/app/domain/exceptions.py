"""Domain-level errors — framework-free, translated to HTTP in app/main.py.

Keep this hierarchy shallow and behavior-driven: a new error type should only
exist if it needs a *different* HTTP outcome or a distinct audit-log event
type, not just because it has a different message.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for every error raised out of the domain/service layers."""


class AlreadyExistsError(DomainError):
    """A create/rename operation collided with an existing unique value — 409."""


class EmailAlreadyExistsError(AlreadyExistsError):
    """Registration attempted with an email already in use."""


class OrganizationAlreadyExistsError(AlreadyExistsError):
    """An organization with this slug already exists."""


class UserAlreadyMemberError(AlreadyExistsError):
    """The user is already a member of this organization."""


class MfaAlreadyEnabledError(AlreadyExistsError):
    """MFA setup/confirm was attempted on an account that already has it enabled."""


class ResourceAlreadyExistsError(AlreadyExistsError):
    """A resource with this name already exists."""


class RoleAlreadyExistsError(AlreadyExistsError):
    """A global role with this code already exists."""


class PolicyAlreadyExistsError(AlreadyExistsError):
    """A policy with this name already exists."""


class GoogleAccountConflictError(AlreadyExistsError):
    """This email is already linked to a *different* Google account — refuse to
    silently reassign which Google identity owns a local user."""


class ForbiddenError(DomainError):
    """The caller is authenticated but not allowed to perform this action — 403."""


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
        super().__init__(
            f"Rate limit exceeded. Retry after {retry_after_seconds} seconds."
        )


class TenantSelectionRequiredError(DomainError):
    """Login succeeded but the user belongs to more than one organization and
    no ``tenant_id`` was given to disambiguate — 409, carrying the list of
    organizations the caller can retry the login with."""

    def __init__(self, organizations: list[dict]) -> None:
        self.organizations = organizations
        super().__init__(
            "Multiple tenants available for this account; specify tenant_id to continue"
        )


class UserNotFoundError(DomainError):
    pass


class OrganizationNotFoundError(DomainError):
    pass


class RoleNotFoundError(DomainError):
    pass


class PermissionNotFoundError(DomainError):
    pass


class ResourceNotFoundError(DomainError):
    pass


class PolicyNotFoundError(DomainError):
    pass


class InvitationNotFoundError(DomainError):
    pass


class MfaNotEnabledError(DomainError):
    """MFA confirm/disable/login-verify was attempted without an active
    (or pending) enrollment to act on."""


class RoleNotAssignedError(DomainError):
    """The user does not currently hold the role being revoked/queried."""


class RoleInUseError(AlreadyExistsError):
    """A role can't be deleted while it's still assigned to at least one user."""


class LastOwnerError(AlreadyExistsError):
    """An organization can't be left without at least one owner — refuse to
    remove or demote its last remaining owner."""


class InvalidPolicyConditionsError(DomainError):
    """A policy's ``conditions`` tree is structurally malformed — 400."""


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
