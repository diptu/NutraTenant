"""Registration, password auth, refresh rotation, logout, Google OIDC federation."""

from __future__ import annotations

from datetime import UTC, datetime

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
    LinksOut,
    LoginRequest,
    LoginUserOut,
    MfaConfirmRequest,
    MfaConfirmResponse,
    MfaDisableRequest,
    MfaLoginVerifyRequest,
    MfaSetupResponse,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    RoleOut,
    SessionOut,
    TenantOut,
    TokenResponse,
    UserOut,
)
from app.core.config import Settings, get_settings
from app.domain.exceptions import GoogleConsentDeniedError, InvalidTokenError
from app.infrastructure.db.models.user import User
from app.infrastructure.security.device import describe_device
from app.services.auth_service import AuthService, LoginResult
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


def _account_status(user: User) -> str:
    # SQLite (tests only) round-trips `locked_until` tz-naive; Postgres
    # round-trips tz-aware — normalize before comparing, same as
    # AuthService._aware.
    locked_until = user.locked_until
    if locked_until is not None and locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=UTC)
    if locked_until is not None and locked_until > datetime.now(UTC):
        return "LOCKED"
    return "ACTIVE" if user.is_active else "INACTIVE"


def _build_token_response(
    result: LoginResult, *, ip_address: str | None, user_agent: str | None, settings: Settings
) -> TokenResponse:
    """Shared by /login and /mfa/login-verify — both produce a LoginResult,
    either an MFA challenge or a completed session, and both render to the
    same contract."""
    if result.mfa_required:
        return TokenResponse(
            mfa_required=True,
            mfa_challenge_token=result.mfa_challenge_token,
            message="Multi-factor authentication required",
        )

    assert result.access_token is not None and result.refresh_token is not None
    assert result.session_id is not None
    assert result.session_issued_at is not None
    assert result.session_expires_at is not None

    user = result.user
    tenant = (
        TenantOut(
            id=str(result.organization.id),
            tenant_id=result.organization.slug,
            name=result.organization.name,
        )
        if result.organization
        else None
    )
    role = (
        RoleOut(id=str(result.role.id), name=result.role.name) if result.role else None
    )

    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
        mfa_required=False,
        user=LoginUserOut(
            id=user.id,
            name=user.full_name,
            email=user.email,
            username=user.email.split("@", 1)[0],
            tenant=tenant,
            role=role,
            department=user.attributes.get("department"),
            clearance_level=user.attributes.get("clearance_level"),
            permissions=result.permissions,
            attributes={
                **user.attributes,
                "account_status": _account_status(user),
                "uses_mfa": user.mfa_enabled,
            },
        ),
        session=SessionOut(
            session_id=f"sess_{result.session_id}",
            issued_at=result.session_issued_at,
            expires_at=result.session_expires_at,
            ip_address=ip_address,
            device=describe_device(user_agent),
            last_login=result.previous_last_login_at,
        ),
        links=LinksOut(
            profile=f"/api/v1/users/{user.id}",
            refresh="/api/v1/auth/refresh",
            logout="/api/v1/auth/logout",
        ),
    )


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
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    result = await auth_service.login(
        email=payload.email,
        password=payload.password,
        ip_address=ip_address,
        user_agent=user_agent,
        tenant_id=payload.tenant_id,
    )
    if not result.mfa_required:
        assert result.refresh_token is not None
        _set_refresh_cookie(response, result.refresh_token, settings)
    return _build_token_response(
        result, ip_address=ip_address, user_agent=user_agent, settings=settings
    )


@router.post("/mfa/login-verify", response_model=TokenResponse)
async def mfa_login_verify(
    payload: MfaLoginVerifyRequest,
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Exchanges the `mfa_challenge_token` from a `mfa_required` login
    response, plus a live TOTP/recovery code, for real tokens."""
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    result = await auth_service.verify_mfa_and_login(
        mfa_challenge_token=payload.mfa_challenge_token,
        code=payload.code,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    assert result.refresh_token is not None
    _set_refresh_cookie(response, result.refresh_token, settings)
    return _build_token_response(
        result, ip_address=ip_address, user_agent=user_agent, settings=settings
    )


@router.post("/mfa/setup", response_model=MfaSetupResponse)
async def setup_mfa(
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> MfaSetupResponse:
    """Starts (or restarts) TOTP enrollment — not active until `confirm_mfa`
    verifies a code against the returned secret."""
    secret, otpauth_uri = await auth_service.setup_mfa(user_id=current_user.id)
    return MfaSetupResponse(secret=secret, otpauth_uri=otpauth_uri)


@router.post("/mfa/confirm", response_model=MfaConfirmResponse)
async def confirm_mfa(
    payload: MfaConfirmRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> MfaConfirmResponse:
    recovery_codes = await auth_service.confirm_mfa(
        user_id=current_user.id, code=payload.code
    )
    return MfaConfirmResponse(recovery_codes=recovery_codes)


@router.post("/mfa/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable_mfa(
    payload: MfaDisableRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    await auth_service.disable_mfa(
        user_id=current_user.id,
        current_password=payload.current_password,
        code=payload.code,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    payload: RefreshRequest | None = None,
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    # Cookie is the primary transport (browser clients); the body field is
    # the fallback for clients that received the refresh token in the
    # /login JSON response instead and have no cookie jar — see RefreshRequest.
    refresh_token = request.cookies.get(_REFRESH_COOKIE_NAME) or (
        payload.refresh_token if payload else None
    )
    if not refresh_token:
        raise InvalidTokenError("Missing refresh token")

    token_pair = await auth_service.refresh(
        refresh_token=refresh_token,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    _set_refresh_cookie(response, token_pair.refresh_token, settings)
    return TokenResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


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
