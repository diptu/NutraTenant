"""FastAPI application factory."""

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from app.api.v1.routes import (
    auth,
    organizations,
    permissions,
    policies,
    resources,
    roles,
    users,
)
from app.core.config import get_settings
from app.core.context_middleware import ContextExtractionMiddleware
from app.core.logging import RequestIDMiddleware, configure_logging
from app.core.metrics import MetricsMiddleware, render_metrics
from app.core.security_headers import SecurityHeadersMiddleware
from app.domain.exceptions import (
    AccountLockedError,
    AlreadyExistsError,
    DomainError,
    ForbiddenError,
    InvalidCredentialsError,
    InvalidMfaCodeError,
    InvalidTokenError,
    InvitationNotFoundError,
    OrganizationNotFoundError,
    PermissionNotFoundError,
    PolicyNotFoundError,
    RateLimitExceededError,
    ResourceNotFoundError,
    RoleNotAssignedError,
    RoleNotFoundError,
    TenantSelectionRequiredError,
    UserNotFoundError,
)

_NOT_FOUND_ERRORS = (
    UserNotFoundError,
    OrganizationNotFoundError,
    RoleNotFoundError,
    PermissionNotFoundError,
    ResourceNotFoundError,
    PolicyNotFoundError,
    RoleNotAssignedError,
    InvitationNotFoundError,
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

    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(users.router, prefix="/api/v1")
    app.include_router(organizations.router, prefix="/api/v1")
    app.include_router(roles.router, prefix="/api/v1")
    app.include_router(permissions.router, prefix="/api/v1")
    app.include_router(resources.router, prefix="/api/v1")
    app.include_router(policies.router, prefix="/api/v1")

    return app


app = create_app()
