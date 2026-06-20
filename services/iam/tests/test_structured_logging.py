"""Tests for structured logging configuration and request-ID middleware."""

from __future__ import annotations

import pytest

from app.core.logging import configure_logging


class TestConfigureLogging:
    def test_configure_logging_debug(self) -> None:
        configure_logging("DEBUG")

    def test_configure_logging_info(self) -> None:
        configure_logging("INFO")

    def test_configure_logging_warning(self) -> None:
        configure_logging("WARNING")

    def test_configure_logging_invalid_level_falls_back(self) -> None:
        # Unknown level should not raise — getattr returns default (INFO)
        configure_logging("NOTAVALIDLEVEL")


class TestRequestLoggingMiddleware:
    @pytest.mark.anyio
    async def test_response_has_request_id_header(self, client) -> None:
        response = await client.get("/health")
        assert response.status_code == 200
        assert "x-request-id" in response.headers

    @pytest.mark.anyio
    async def test_incoming_request_id_is_echoed(self, client) -> None:
        custom_id = "my-trace-id-abc123"
        response = await client.get("/health", headers={"X-Request-ID": custom_id})
        assert response.headers["x-request-id"] == custom_id

    @pytest.mark.anyio
    async def test_generated_request_id_is_uuid_like(self, client) -> None:
        response = await client.get("/health")
        rid = response.headers.get("x-request-id", "")
        # UUIDs are 36 chars: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
        assert len(rid) == 36
        assert rid.count("-") == 4

    @pytest.mark.anyio
    async def test_different_requests_get_different_ids(self, client) -> None:
        r1 = await client.get("/health")
        r2 = await client.get("/health")
        assert r1.headers["x-request-id"] != r2.headers["x-request-id"]
