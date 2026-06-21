"""FastAPI dependency providers — DB session, caches, services, current-user."""

from __future__ import annotations

from app.core.cache import PermissionCache, get_permission_cache
from app.core.config import Settings, get_settings
from app.core.rate_limit import RateLimiter, get_rate_limiter
from app.core.token_blacklist import TokenBlacklist, get_token_blacklist
from app.domain.exceptions import ForbiddenError, InvalidTokenError
from app.infrastructure.db.models.user import User
from app.infrastructure.db.repositories.role_repo import RoleRepository
from app.infrastructure.db.repositories.user_repo import UserRepository
from app.infrastructure.db.repositories.user_role_repo import UserRoleRepository
from app.infrastructure.db.session import get_db as get_async_db
from app.infrastructure.security.google_oidc import GoogleOIDCClient
from app.infrastructure.security.jwt import AccessTokenClaims, decode_access_token
from app.infrastructure.security.oauth_state_store import OAuthStateStore
from app.infrastructure.security.token_cache import RedisTokenCache, TokenCache
from app.services.auth_service import AuthService
from app.services.google_oauth_service import GoogleOAuthService
from app.services.organization_service import OrganizationService
from app.services.policy_engine_service import PolicyEngineService
from app.services.policy_service import PolicyService
from app.services.resource_service import ResourceService
from app.services.role_service import RoleService
from app.services.tenant_service import TenantService
from app.services.user_service import UserService
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "get_async_db",
    "get_auth_service",
    "get_current_access_claims",
    "get_current_user",
    "get_google_oauth_service",
    "get_oidc_client",
    "get_organization_service",
    "get_policy_engine_service",
    "get_policy_service",
    "get_resource_service",
    "get_role_service",
    "get_state_store",
    "get_tenant_service",
    "get_token_cache",
    "get_user_service",
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
    """For routes that need the *session's* tenant_id/role claims, not just
    the caller's identity — e.g. verifying a request is scoped to the tenant
    its access token was minted for, independent of whether the user also
    happens to be a member of other tenants."""
    return await _validate_access_claims(credentials, settings, blacklist)


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


def get_user_service(session: AsyncSession = Depends(get_async_db)) -> UserService:
    return UserService(session)


def get_organization_service(
    session: AsyncSession = Depends(get_async_db),
    permission_cache: PermissionCache = Depends(get_permission_cache),
    settings: Settings = Depends(get_settings),
) -> OrganizationService:
    return OrganizationService(session, permission_cache, settings)


def get_resource_service(
    session: AsyncSession = Depends(get_async_db),
) -> ResourceService:
    return ResourceService(session)


def get_role_service(session: AsyncSession = Depends(get_async_db)) -> RoleService:
    return RoleService(session)


def get_policy_service(session: AsyncSession = Depends(get_async_db)) -> PolicyService:
    return PolicyService(session)


def get_policy_engine_service(
    session: AsyncSession = Depends(get_async_db),
) -> PolicyEngineService:
    return PolicyEngineService(session)


def get_tenant_service(session: AsyncSession = Depends(get_async_db)) -> TenantService:
    return TenantService(session)
