"""JWT-claims-in-request.state + a permissions-in-JWT authorization dependency.

Standalone and purely additive — not applied to any production route in
this service. Provided as available primitives (and exercised directly in
tests/test_authorization_engine.py via a small standalone app) for routes
that want permissions embedded directly in the access token itself, as an
alternative to the DB-resolved RBAC/ABAC paths elsewhere in this service.

The middleware never rejects a request itself — it only decodes (or fails
to decode) the bearer token and stashes the result; `require_permission`
is what turns "no usable claims" into a 401 and "claims present but missing
the permission" into a 403, so auth failures and authorization failures
stay cleanly distinguishable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import jwt
from app.core.config import get_settings
from app.modules.auth.exceptions import InvalidTokenError
from app.shared.exceptions.base import ForbiddenError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


def _decode_claims(request: Request) -> dict[str, Any] | None:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.removeprefix("Bearer ")

    settings = get_settings()
    try:
        claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None

    if claims.get("type") != "access":
        return None
    return claims


class JWTContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.claims = _decode_claims(request)
        return await call_next(request)


def require_permission(code: str):
    """Reads the claims JWTContextMiddleware already decoded — falls back to
    decoding inline if the middleware isn't installed on this app, so the
    dependency works standalone too."""

    async def _check(request: Request) -> dict[str, Any]:
        claims = getattr(request.state, "claims", None)
        if claims is None:
            claims = _decode_claims(request)
        if claims is None:
            raise InvalidTokenError("Missing or invalid access token")
        if code not in claims.get("permissions", []):
            raise ForbiddenError(f"Missing required permission: '{code}'")
        return claims

    return _check
