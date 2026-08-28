"""Task 55 slice 1 — usage_records + billing APIs."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext
from backend.core.billing.context import bind_billing_context, clear_billing_context
from backend.core.billing.usage import make_idempotency_key, record_metered_usage
from apps.api.routers import billing as billing_mod
from apps.api.routers.billing import router as billing_router


@pytest.fixture(autouse=True)
def _clear_billing_ctx() -> None:
    clear_billing_context()
    yield
    clear_billing_context()


@pytest.fixture
def tenant_admin() -> TenantContext:
    return TenantContext("acme", "u1", "tenant_admin", [], False)


def test_make_idempotency_key_truncates() -> None:
    key = make_idempotency_key(trace_id="tr_abc", model="gpt-4o", suffix="llm")
    assert key == "tr_abc:gpt-4o:llm"
    assert len(key) <= 128


def test_record_metered_usage_skips_without_user() -> None:
    assert record_metered_usage(
        tenant_id="acme",
        model="gpt-4o",
        input_tokens=10,
        output_tokens=5,
        cost=0.01,
    ) is False


def test_record_metered_usage_inserts(monkeypatch) -> None:
    captured: dict = {}

    class _Sess:
        def execute(self, sql, params=None):
            captured["sql"] = str(sql)
            captured["params"] = dict(params or {})
            return MagicMock()

        def commit(self) -> None:
            captured["committed"] = True

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return None

    factory = MagicMock()
    factory.Session.return_value = _Sess()
    monkeypatch.setattr(
        "backend.core.billing.usage.get_pg_session", lambda: factory
    )
    bind_billing_context(user_id="u1", trace_id="tr_x", key_id="7")

    ok = record_metered_usage(
        tenant_id="acme",
        model="deepseek-v4-flash",
        input_tokens=100,
        output_tokens=50,
        cost=0.021,
        provider="deepseek",
    )
    assert ok is True
    assert captured.get("committed") is True
    p = captured["params"]
    assert p["tenant_id"] == "acme"
    assert p["user_id"] == "u1"
    assert p["trace_id"] == "tr_x"
    assert p["credential_kind"] == "company"
    assert p["key_id"] == "7"
    assert p["input_tokens"] == 100
    assert p["output_tokens"] == 50
    assert p["cost"] == Decimal("0.021")


def test_usage_summary_api(monkeypatch, tenant_admin: TenantContext) -> None:
    totals = SimpleNamespace(calls=2, input_tokens=30, output_tokens=20, cost=0.15)
    by_model = [
        SimpleNamespace(
            model="gpt-4o",
            credential_kind="company",
            calls=2,
            input_tokens=30,
            output_tokens=20,
            cost=0.15,
        )
    ]
    call_idx = {"n": 0}

    class _Sess:
        def execute(self, sql, params=None):
            q = MagicMock()
            sql_s = str(sql)
            if "GROUP BY" in sql_s:
                q.fetchall = lambda: by_model
            else:
                q.fetchone = lambda: totals
            call_idx["n"] += 1
            return q

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return None

    factory = MagicMock()
    factory.Session.return_value = _Sess()
    monkeypatch.setattr(billing_mod, "get_pg_session", lambda: factory)

    app = FastAPI()
    app.include_router(billing_router, prefix="/api")

    async def _auth() -> TenantContext:
        return tenant_admin

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    r = TestClient(app).get("/api/billing/usage/summary?billing_month=2026-08")
    assert r.status_code == 200
    body = r.json()
    assert body["totals"]["calls"] == 2
    assert body["by_model"][0]["model"] == "gpt-4o"


def test_usage_detail_denied_for_user() -> None:
    user = TenantContext("acme", "u1", "user", [], False)
    app = FastAPI()
    app.include_router(billing_router, prefix="/api")

    async def _auth() -> TenantContext:
        return user

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    r = TestClient(app).get("/api/billing/usage/detail")
    assert r.status_code == 403
