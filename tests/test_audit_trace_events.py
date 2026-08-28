"""GET /api/audit/trace/{trace_id}/events — read-tier replay (Task 63 拍板 1A)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext
from apps.api.routers import audit as audit_mod
from apps.api.routers.audit import router as audit_router


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext("acme", "u1", "user", [], False)


def test_trace_events_requires_read_not_export(monkeypatch, tenant: TenantContext) -> None:
    row = SimpleNamespace(
        id=1,
        tenant_id="acme",
        user_id="u1",
        action="memory.rag_sanitize",
        trace_id="tr-99",
        parent_trace_id=None,
        tool_use_id=None,
        decision_explain=None,
        input_text="hi",
        output_text='{"rag_retrieved_ids":["d1"]}',
        input_text_enc=None,
        output_text_enc=None,
        text_enc_version=None,
        model="memory",
        input_tokens=0,
        output_tokens=0,
        cost=0.0,
        latency_ms=None,
        error_code=None,
        ip_address=None,
        user_agent=None,
        created_at=datetime(2026, 8, 22, 12, 0, 0),
        _mapping=None,
    )
    row._mapping = {  # type: ignore[attr-defined]
        k: getattr(row, k)
        for k in (
            "id",
            "tenant_id",
            "user_id",
            "action",
            "trace_id",
            "parent_trace_id",
            "tool_use_id",
            "decision_explain",
            "input_text",
            "output_text",
            "input_text_enc",
            "output_text_enc",
            "text_enc_version",
            "model",
            "input_tokens",
            "output_tokens",
            "cost",
            "latency_ms",
            "error_code",
            "ip_address",
            "user_agent",
            "created_at",
        )
    }

    class _Sess:
        def execute(self, sql, params=None):
            q = MagicMock()
            q.fetchall = lambda: [row]
            return q

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return None

    factory = MagicMock()
    factory.Session.return_value = _Sess()
    monkeypatch.setattr(audit_mod, "get_pg_session", lambda: factory)
    monkeypatch.setattr(audit_mod, "audit_user_filter", lambda *_a, **_k: (None, {}))

    app = FastAPI()
    app.include_router(audit_router, prefix="/api")

    async def _auth() -> TenantContext:
        return tenant

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    r = TestClient(app).get("/api/audit/trace/tr-99/events")
    assert r.status_code == 200
    body = r.json()
    assert body["trace_id"] == "tr-99"
    assert body["count"] >= 1
    assert body["events"][0]["type"] == "memory_event"
    assert "d1" in str(body["events"][0].get("output_preview", ""))
