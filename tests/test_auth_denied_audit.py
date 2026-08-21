"""Task 52 P1-7 auth deny writes audit."""

from __future__ import annotations

import asyncio

from starlette.exceptions import HTTPException
from starlette.requests import Request

from backend.core.errors import http_exception_audit_handler


def test_http_401_writes_audit(monkeypatch) -> None:
    seen: list[dict] = []

    def _write(record: dict) -> bool:
        seen.append(record)
        return True

    monkeypatch.setattr("backend.core.audit.write_audit_sync", _write)
    req = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    exc = HTTPException(status_code=401, detail="missing_key")
    resp = asyncio.run(http_exception_audit_handler(req, exc))
    assert resp.status_code == 401
    assert seen
    assert seen[0]["action"] == "auth_denied"
    assert seen[0]["error_code"] == "HTTP_401"
    assert seen[0]["input_text"] == ""
