"""Task 59 S2 — unified internal error responses."""

from __future__ import annotations

import asyncio

import pytest
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from packages.errors import (
    http_exception_audit_handler,
    internal_error_payload,
)


def _req(trace_id: str = "trace-abc") -> Request:
    scope = {"type": "http", "method": "GET", "path": "/", "headers": []}

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(scope, receive)
    request.state.trace_id = trace_id
    return request


def test_internal_error_payload_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    payload = internal_error_payload(_req(), RuntimeError("db connection failed"))
    assert payload["code"] == "INTERNAL"
    assert payload["trace_id"] == "trace-abc"
    assert "db connection" not in str(payload)


def test_http_500_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    exc = StarletteHTTPException(status_code=500, detail="leaked stack /path")
    resp = asyncio.run(http_exception_audit_handler(_req(), exc))
    body = resp.body.decode()
    assert "leaked stack" not in body
    assert "INTERNAL" in body
