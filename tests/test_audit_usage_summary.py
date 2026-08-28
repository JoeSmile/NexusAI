"""GET /api/audit/usage-summary — today's tokens/cost, no transcript."""

from __future__ import annotations

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


def test_usage_summary_aggregates(monkeypatch, tenant: TenantContext) -> None:
    totals = SimpleNamespace(calls=4, input_tokens=20, output_tokens=30, cost=0.5)
    cfg = SimpleNamespace(config={"budget": {"daily_limit": 12.0}})
    captured: dict = {}

    class _Sess:
        def execute(self, sql, params=None):
            q = MagicMock()
            sql_s = str(sql)
            if "SUM(cost)" in sql_s:
                captured["sql"] = sql_s
                captured["params"] = dict(params or {})
                q.fetchone = lambda: totals
            else:
                q.fetchone = lambda: cfg
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
    r = TestClient(app).get("/api/audit/usage-summary")
    assert r.status_code == 200
    body = r.json()
    assert body["calls"] == 4
    assert body["tokens"] == 50
    assert body["cost"] == 0.5
    assert body["daily_limit"] == 12.0
    assert "input_text" not in body
    assert "action" in (captured.get("sql") or "")
    assert captured.get("params", {}).get("chat_action") == "chat"
