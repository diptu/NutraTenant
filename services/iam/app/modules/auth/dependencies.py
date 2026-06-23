"""Auth dependency providers — current-user/claims resolution, the coarse
RBAC guards every other domain's router depends on, and the auth/Google
service providers. `get_current_user`/`require_superuser`/`require_global_role`/
`get_current_access_claims` are imported by every other domain's `router.py`,
the same way they were imported from the old monolithic
`app.api.v1.dependencies` before this split.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.core.rate_limit import RateLimiter, get_rate_limiter
from app.core.token_blacklist import TokenBlacklist, get_token_blacklist
from app.infrastructure.database.session import get_db as get_async_db
from app.modules.auth.exceptions import InvalidTokenError
from app.modules.auth.google_service import GoogleOAuthService
from app.modules.auth.repositories.sqlalchemy.token_repository import RefreshTokenRepository
from app.modules.auth.service import AuthService
from app.modules.auth.utils.jwt import AccessTokenClaims, decode_access_token
from app.modules.auth.utils.oauth import GoogleOIDCClient, OAuthStateStore, RedisTokenCache, TokenCache
from app.modules.organizations.repositories.sqlalchemy.organization_repository import (
    OrganizationRepository,
)
from app.modules.roles.repositories.sqlalchemy.role_repository import (
    RoleRepository,
    UserRoleRepository,
)
from app.modules.users.models import User
from app.modules.users.repositories.sqlalchemy.user_repository import UserRepository
from app.shared.exceptions.base import ForbiddenError
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "get_async_db",
    "get_auth_service",
    "get_current_access_claims",
    "get_current_tenant_slug",
    "get_current_user",
    "get_google_oauth_service",
    "get_oidc_client",
    "get_state_store",
    "get_token_cache",
    "require_global_role",
    "require_superuser",
]

_bearer_scheme = HTTPBearer(auto_error=True)

_redis_singleton: Redis | None = None
_oidc_client_singleton: GoogleOIDCClient | None = None


def _get_redis(settings: Settings) -> Redis:
    global _redis_singleton
    if _redis_singleton is None:
        _redis_singleton = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_singleton


def get_token_cache(settings: Settings = Depends(get_settings)) -> TokenCache:
    return RedisTokenCache(_get_redis(settings))


def get_oidc_client(settings: Settings = Depends(get_settings)) -> GoogleOIDCClient:
    """Process-wide singleton, same pattern as `_get_redis` above —
    GoogleOIDCClient holds a JWKS cache that needs to survive across
    requests; constructing a fresh client (and thus a fresh, empty JWKS
    cache) on every request meant the cache could never actually save a
    Google round-trip. `Settings` isn't hashable, so this can't just be
    `@lru_cache`'d like get_settings() itself."""
    global _oidc_client_singleton
    if _oidc_client_singleton is None:
        _oidc_client_singleton = GoogleOIDCClient(settings)
    return _oidc_client_singleton


def reset_oidc_client() -> None:
    global _oidc_client_singleton
    _oidc_client_singleton = None


def get_state_store(
    settings: Settings = Depends(get_settings),
    cache: TokenCache = Depends(get_token_cache),
) -> OAuthStateStore:
    return OAuthStateStore(cache, ttl_seconds=settings.google_oauth_state_ttl_seconds)


def get_auth_service(
    session: AsyncSession = Depends(get_async_db),
    settings: Settings = Depends(get_settings),
    blacklist: TokenBlacklist = Depends(get_token_blacklist),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> AuthService:
    return AuthService(session, settings, blacklist, rate_limiter)


def get_google_oauth_service(
    session: AsyncSession = Depends(get_async_db),
    settings: Settings = Depends(get_settings),
    oidc_client: GoogleOIDCClient = Depends(get_oidc_client),
    state_store: OAuthStateStore = Depends(get_state_store),
    auth_service: AuthService = Depends(get_auth_service),
) -> GoogleOAuthService:
    return GoogleOAuthService(
        session,
        settings,
        oidc_client=oidc_client,
        state_store=state_store,
        auth_service=auth_service,
    )


async def _validate_access_claims(
    credentials: HTTPAuthorizationCredentials,
    settings: Settings,
    blacklist: TokenBlacklist,
) -> AccessTokenClaims:
    claims = decode_access_token(settings, credentials.credentials)

    if await blacklist.contains_jti(str(claims.jti)):
        raise InvalidTokenError("Access token has been revoked")

    invalidate_before = await blacklist.get_invalidate_before(str(claims.subject_id))
    if invalidate_before is not None and claims.issued_at.timestamp() < invalidate_before:
        raise InvalidTokenError("Access token was issued before the account's last credential change")
    return claims


async def get_current_access_claims(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
    blacklist: TokenBlacklist = Depends(get_token_blacklist),
) -> AccessTokenClaims:
    """For routes that need the raw access-token claims (e.g. its
    ``session_id``, to resolve tenant context via
    ``get_current_tenant_slug``), not just the caller's identity."""
    return await _validate_access_claims(credentials, settings, blacklist)


async def get_current_tenant_slug(
    claims: AccessTokenClaims = Depends(get_current_access_claims),
    session: AsyncSession = Depends(get_async_db),
) -> str | None:
    """The organization slug the *caller's current session* is bound to —
    resolved dynamically from the session row (``claims.session_id``,
    a ``RefreshToken.id``) rather than trusted off an embedded JWT claim,
    per BackendSkill/How-to-auth-api.md's "load dynamically, don't embed"
    rule. Returns ``None`` for a session with no tenant context (e.g. a
    superuser, or a user with zero memberships at login time)."""
    stored = await RefreshTokenRepository(session).get_by_id(claims.session_id)
    if stored is None or stored.organization_id is None:
        return None
    organization = await OrganizationRepository(session).get_by_id(stored.organization_id)
    return organization.slug if organization is not None else None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_async_db),
    settings: Settings = Depends(get_settings),
    blacklist: TokenBlacklist = Depends(get_token_blacklist),
) -> User:
    claims = await _validate_access_claims(credentials, settings, blacklist)

    user = await UserRepository(session).get_by_id(claims.subject_id)
    if user is None or not user.is_active:
        raise InvalidTokenError("User no longer exists or is inactive")
    return user


def require_superuser(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_superuser:
        raise ForbiddenError("This action requires administrator privileges")
    return current_user


def require_global_role(code: str):
    """Fast-path coarse RBAC guard — a single indexed lookup against the
    global `user_roles` table, no ABAC evaluation. Superusers always pass."""

    async def _check(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_async_db),
    ) -> User:
        if current_user.is_superuser:
            return current_user

        role = await RoleRepository(session).get_by_code(code)
        if role is None or not await UserRoleRepository(session).has_role(current_user.id, role.id):
            raise ForbiddenError(f"This action requires the '{code}' role")
        return current_user

    return _check
