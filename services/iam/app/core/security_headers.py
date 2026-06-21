"""Baseline security response headers — applied to every response."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.core.config import get_settings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}
_HSTS_HEADER = "max-age=63072000; includeSubDomains"

# The JSON API never needs to load anything — lock it down completely.
_API_CSP = "default-src 'none'; frame-ancestors 'none'"

# FastAPI's interactive docs (/docs, /redoc) render Swagger UI/ReDoc, which
# pull their JS/CSS from jsdelivr and run an inline bootstrap script —
# `default-src 'none'` blocks all of that. Scope the relaxation to exactly
# the docs routes rather than loosening the CSP for the whole API.
_DOCS_CSP = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "font-src 'self' https://cdn.jsdelivr.net; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
)
_DOCS_PATHS = {"/docs", "/redoc", "/docs/oauth2-redirect"}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for header, value in _BASE_HEADERS.items():
            response.headers.setdefault(header, value)
        # HSTS on a plain-http origin (local dev) just breaks the next
        # request without adding any protection — gate it on the same
        # setting that controls whether cookies are marked Secure.
        if get_settings().cookie_secure:
            response.headers.setdefault("Strict-Transport-Security", _HSTS_HEADER)
        csp = _DOCS_CSP if request.url.path in _DOCS_PATHS else _API_CSP
        response.headers.setdefault("Content-Security-Policy", csp)
        return response
