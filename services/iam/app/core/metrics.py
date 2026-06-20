"""Prometheus-format /metrics scrape target — stdlib only, no extra dependency.

Module-level counters (not a FastAPI dependency) mirror the
`get_rate_limiter()`/`reset_rate_limiter()` singleton shape elsewhere in
`app.core`, so tests can reset state between runs via `reset_metrics()`.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_DURATION_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    float("inf"),
)

_request_counts: dict[tuple[str, str, str], int] = defaultdict(int)
_duration_sum: dict[tuple[str, str], float] = defaultdict(float)
_duration_count: dict[tuple[str, str], int] = defaultdict(int)
_duration_buckets: dict[tuple[str, str, float], int] = defaultdict(int)


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    return route.path if route is not None else request.url.path


def record_request(
    method: str, path: str, status_code: int, duration_seconds: float
) -> None:
    _request_counts[(method, path, str(status_code))] += 1
    key = (method, path)
    _duration_sum[key] += duration_seconds
    _duration_count[key] += 1
    for bucket in _DURATION_BUCKETS:
        if duration_seconds <= bucket:
            _duration_buckets[(method, path, bucket)] += 1
            break


def reset_metrics() -> None:
    """Test-only hook to clear counters between test runs."""
    _request_counts.clear()
    _duration_sum.clear()
    _duration_count.clear()
    _duration_buckets.clear()


def render_metrics() -> str:
    lines = [
        "# HELP iam_http_requests_total Total HTTP requests processed.",
        "# TYPE iam_http_requests_total counter",
    ]
    for (method, path, status_code), count in sorted(_request_counts.items()):
        lines.append(
            f'iam_http_requests_total{{method="{method}",path="{path}",'
            f'status_code="{status_code}"}} {count}'
        )

    lines.append(
        "# HELP iam_http_request_duration_seconds HTTP request duration in seconds."
    )
    lines.append("# TYPE iam_http_request_duration_seconds histogram")
    for method, path in sorted(_duration_count):
        cumulative = 0
        for bucket in _DURATION_BUCKETS:
            cumulative += _duration_buckets.get((method, path, bucket), 0)
            le_label = "+Inf" if bucket == float("inf") else str(bucket)
            lines.append(
                f'iam_http_request_duration_seconds_bucket{{method="{method}",'
                f'path="{path}",le="{le_label}"}} {cumulative}'
            )
        lines.append(
            f'iam_http_request_duration_seconds_sum{{method="{method}",'
            f'path="{path}"}} {_duration_sum[(method, path)]}'
        )
        lines.append(
            f'iam_http_request_duration_seconds_count{{method="{method}",'
            f'path="{path}"}} {_duration_count[(method, path)]}'
        )

    return "\n".join(lines) + "\n"


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        record_request(
            request.method, _route_template(request), response.status_code, duration
        )
        return response
