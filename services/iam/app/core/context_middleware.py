"""Environmental context extraction — the ABAC engine's ``context`` namespace.

Runs as real ASGI middleware (so it fires for *every* request, not just
ones that happen to declare a dependency on it) and stashes the result on
``request.state.context``; ``get_request_context`` just reads that back out
for route handlers / the policy engine to consume.

Purely additive: it never raises, never blocks a request, and doesn't
change any existing route's behavior — it only makes data available to
whatever chooses to read it.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import Settings, get_settings


def extract_client_ip(request: Request) -> str:
    """Prefers `X-Forwarded-For` (set by a reverse proxy/load balancer in front
    of this service) over the raw socket peer, which would otherwise just be
    the proxy's own address."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def is_in_corporate_range(ip: str, cidrs: list[str]) -> bool:
    if not cidrs:
        return False
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if address in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def resolve_geo_stub(ip: str) -> dict[str, Any]:
    """Placeholder for a real geo-IP provider (MaxMind, ipapi, ...) — none is
    wired up (this is a $0-cost stack with no paid geo-IP subscription), so
    this always returns the same deterministic "unknown" shape. Swap the
    body of this function out for a real lookup without touching any caller."""
    return {"country": "unknown", "region": "unknown", "ip": ip}


def build_context(request: Request, settings: Settings) -> dict[str, Any]:
    ip = extract_client_ip(request)
    return {
        "ip_address": ip,
        "timestamp": datetime.now(UTC).isoformat(),
        "geo": resolve_geo_stub(ip),
        "ip_in_corporate_range": is_in_corporate_range(ip, settings.corporate_ip_cidrs),
        "user_agent": request.headers.get("user-agent"),
    }


class ContextExtractionMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.context = build_context(request, get_settings())
        return await call_next(request)


def get_request_context(request: Request) -> dict[str, Any]:
    return getattr(request.state, "context", None) or build_context(
        request, get_settings()
    )
