"""Task 52 P2-9 production 500 has no internal detail."""

from __future__ import annotations

import asyncio

from starlette.requests import Request

from packages.errors import global_exception_handler


def _req() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


def test_production_500_hides_detail(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEBUG", "true")
    resp = asyncio.run(global_exception_handler(_req(), RuntimeError("secret/path/traceback")))
    body = resp.body.decode()
    assert "secret/path" not in body
    assert "internal_error" in body


def test_debug_nonprod_shows_detail(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("DEBUG", "true")
    resp = asyncio.run(global_exception_handler(_req(), RuntimeError("visible-debug")))
    assert "visible-debug" in resp.body.decode()
