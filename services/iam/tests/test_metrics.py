"""Section 11 (Production Readiness): Prometheus /metrics scrape target."""

from __future__ import annotations

import pytest
from fastapi import status


@pytest.mark.anyio
class TestMetricsEndpoint:
    async def test_metrics_returns_200_in_prometheus_format(self, client) -> None:
        resp = await client.get("/metrics")
        assert resp.status_code == status.HTTP_200_OK
        assert "text/plain" in resp.headers["content-type"]
        assert "iam_http_requests_total" in resp.text
        assert "iam_http_request_duration_seconds" in resp.text

    async def test_metrics_counts_requests_by_route_template(self, client) -> None:
        await client.get("/health")
        await client.get("/health")

        resp = await client.get("/metrics")
        body = resp.text
        assert (
            'iam_http_requests_total{method="GET",path="/health",status_code="200"}'
            in body
        )

    async def test_metrics_excluded_from_openapi_schema(self, client) -> None:
        resp = await client.get("/openapi.json")
        assert "/metrics" not in resp.json()["paths"]
