"""Registration, password auth, refresh rotation, logout, Google OIDC federation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.v1.dependencies import (
    get_auth_service,
    get_current_user,
    get_google_oauth_service,
)
from app.api.v1.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    GoogleAuthorizeResponse,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
)
from app.core.config import Settings, get_settings
from app.domain.exceptions import GoogleConsentDeniedError, InvalidTokenError
from app.infrastructure.db.models.user import User
from app.services.auth_service import AuthService
from app.services.google_oauth_service import GoogleOAuthService

router = APIRouter(prefix="/auth", tags=["auth"])

_REFRESH_COOKIE_NAME = "refresh_token"  # noqa: S105 - cookie name, not a secret
_REFRESH_COOKIE_PATH = "/api/v1/auth"
_optional_bearer = HTTPBearer(auto_error=False)


def _set_refresh_cookie(
    response: Response, refresh_token: str, settings: Settings
) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=settings.refresh_token_expire_days * 86400,
        path=_REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=_REFRESH_COOKIE_NAME, path=_REFRESH_COOKIE_PATH)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> UserOut:
    user = await auth_service.register(
        email=payload.email, password=payload.password, full_name=payload.full_name
    )
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    access_token, refresh_token, _user = await auth_service.login(
        email=payload.email,
        password=payload.password,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    _set_refresh_cookie(response, refresh_token, settings)
    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    refresh_token = request.cookies.get(_REFRESH_COOKIE_NAME)
    if not refresh_token:
        raise InvalidTokenError("Missing refresh token cookie")

    access_token, new_refresh_token = await auth_service.refresh(
        refresh_token=refresh_token,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    _set_refresh_cookie(response, new_refresh_token, settings)
    return TokenResponse(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
) -> None:
    refresh_token = request.cookies.get(_REFRESH_COOKIE_NAME)
    access_token = credentials.credentials if credentials else None
    await auth_service.logout(refresh_token=refresh_token, access_token=access_token)
    _clear_refresh_cookie(response)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    await auth_service.change_password(
        user_id=current_user.id,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> ForgotPasswordResponse:
    """Always 200s with the same generic message regardless of whether `email`
    matched an account — see AuthService.request_password_reset."""
    reset_token = await auth_service.request_password_reset(email=payload.email)
    return ForgotPasswordResponse(reset_token=reset_token)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    payload: ResetPasswordRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    await auth_service.reset_password(
        raw_token=payload.token, new_password=payload.new_password
    )


@router.get("/google/login", response_model=GoogleAuthorizeResponse)
async def google_login(
    google_oauth_service: GoogleOAuthService = Depends(get_google_oauth_service),
) -> GoogleAuthorizeResponse:
    """Returns the Google consent-screen URL for the frontend to redirect to.

    (A JSON body rather than a 302 — this service has no server-rendered
    frontend to redirect *from*; an SPA reads `authorization_url` and
    navigates the browser itself.)
    """
    authorization_url = await google_oauth_service.start()
    return GoogleAuthorizeResponse(authorization_url=authorization_url)


@router.get("/google/login/redirect", include_in_schema=False)
async def google_login_redirect(
    google_oauth_service: GoogleOAuthService = Depends(get_google_oauth_service),
) -> RedirectResponse:
    """Convenience variant that 302s directly, for manual/browser testing."""
    authorization_url = await google_oauth_service.start()
    return RedirectResponse(authorization_url, status_code=status.HTTP_302_FOUND)


@router.get("/google/callback", response_model=TokenResponse)
async def google_callback(
    request: Request,
    response: Response,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    google_oauth_service: GoogleOAuthService = Depends(get_google_oauth_service),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    if error is not None:
        # Google redirects back with `?error=...` (no `code`) when the user
        # denies consent on the Google screen — a real outcome, not an
        # exceptional one, so it's checked before the required-param 422s
        # below would otherwise mask it.
        raise GoogleConsentDeniedError(f"Google sign-in was not completed: {error}")
    if code is None or state is None:
        raise GoogleConsentDeniedError("Missing 'code' or 'state' query parameter")

    access_token, refresh_token, _user = await google_oauth_service.handle_callback(
        code=code,
        state=state,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    _set_refresh_cookie(response, refresh_token, settings)
    return TokenResponse(access_token=access_token)
