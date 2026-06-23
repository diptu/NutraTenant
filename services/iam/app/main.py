"""FastAPI application factory."""

from app.api.v1.router import router as api_v1_router
from app.core.config import get_settings
from app.core.context_middleware import ContextExtractionMiddleware
from app.core.logging import RequestIDMiddleware, configure_logging
from app.core.metrics import MetricsMiddleware, render_metrics
from app.core.security_headers import SecurityHeadersMiddleware
from app.modules.access_governance.exceptions import (
    AccessApprovalNotFoundError,
    AccessRequestNotFoundError,
    AccessReviewNotFoundError,
)
from app.modules.auth.exceptions import (
    AccountLockedError,
    InvalidCredentialsError,
    InvalidMfaCodeError,
    InvalidTokenError,
    RateLimitExceededError,
    SessionNotFoundError,
    TenantSelectionRequiredError,
)
from app.modules.groups.exceptions import GroupMembershipNotFoundError, GroupNotFoundError
from app.modules.organizations.exceptions import (
    InvitationNotFoundError,
    OrganizationNotFoundError,
)
from app.modules.permissions.exceptions import PermissionNotFoundError
from app.modules.policies.exceptions import PolicyNotFoundError
from app.modules.reserved_tenant_ids.exceptions import ReservedTenantIdNotFoundError
from app.modules.resources.exceptions import ResourceNotFoundError
from app.modules.roles.exceptions import RoleNotAssignedError, RoleNotFoundError
from app.modules.tenants.exceptions import (
    OrganizationTenantLinkNotFoundError,
    TenantNotFoundError,
)
from app.modules.users.exceptions import UserNotFoundError
from app.shared.exceptions.base import AlreadyExistsError, DomainError, ForbiddenError
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

_NOT_FOUND_ERRORS = (
    UserNotFoundError,
    OrganizationNotFoundError,
    RoleNotFoundError,
    PermissionNotFoundError,
    ResourceNotFoundError,
    PolicyNotFoundError,
    RoleNotAssignedError,
    InvitationNotFoundError,
    TenantNotFoundError,
    OrganizationTenantLinkNotFoundError,
    SessionNotFoundError,
    GroupNotFoundError,
    GroupMembershipNotFoundError,
    AccessRequestNotFoundError,
    AccessReviewNotFoundError,
    AccessApprovalNotFoundError,
    ReservedTenantIdNotFoundError,
)
_UNAUTHORIZED_ERRORS = (
    InvalidCredentialsError,
    InvalidTokenError,
    InvalidMfaCodeError,
)


async def _domain_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """Safety-net translation of any domain error a route forgot to catch locally.

    Every error a route is expected to surface today is already caught and
    mapped to a specific HTTPException at the call site — this exists only
    so a future service-layer error that isn't yet wrapped degrades to a
    sensible status code instead of an opaque 500.
    """
    assert isinstance(exc, DomainError)
    if isinstance(exc, AccountLockedError):
        return JSONResponse(
            status_code=status.HTTP_423_LOCKED,
            content={"detail": str(exc)},
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )
    if isinstance(exc, RateLimitExceededError):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": str(exc)},
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )
    if isinstance(exc, TenantSelectionRequiredError):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(exc), "organizations": exc.organizations},
        )
    if isinstance(exc, _UNAUTHORIZED_ERRORS):
        status_code = status.HTTP_401_UNAUTHORIZED
    elif isinstance(exc, ForbiddenError):
        status_code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, _NOT_FOUND_ERRORS):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, AlreadyExistsError):
        status_code = status.HTTP_409_CONFLICT
    else:
        status_code = status.HTTP_400_BAD_REQUEST
    return JSONResponse(status_code=status_code, content={"detail": str(exc)})


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging("DEBUG" if settings.debug else "INFO")

    app = FastAPI(title=settings.app_name)

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(ContextExtractionMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        # Matches per-tenant subdomain origins (e.g. apple-corp.localhost:3000)
        # against cors_allowed_base_domains — see Settings.cors_origin_regex.
        allow_origin_regex=settings.cors_origin_regex(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(DomainError, _domain_error_handler)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics", tags=["metrics"], include_in_schema=False)
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse(render_metrics(), media_type="text/plain")

    app.include_router(api_v1_router, prefix="/api/v1")

    return app


app = create_app()
