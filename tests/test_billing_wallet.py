"""Task 55 slice 2 — wallet recharge, deduct, concurrency."""

from __future__ import annotations

import threading
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext
from backend.core.billing.context import bind_billing_context, clear_billing_context
from backend.core.billing.wallet import (
    InsufficientBalanceError,
    check_wallet_allows,
    deduct_balance_in_session,
    get_balance_sync,
    is_wallet_billing_enabled,
    recharge_wallet,
)
from backend.core.harness.llm import LLMHarness
from apps.api.routers import billing as billing_mod
from apps.api.routers.billing import router as billing_router


@pytest.fixture(autouse=True)
def _clear_billing_ctx() -> None:
    clear_billing_context()
    yield
    clear_billing_context()


@pytest.fixture
def tenant_admin() -> TenantContext:
    return TenantContext("acme", "admin1", "tenant_admin", [], False)


def test_wallet_billing_disabled_by_default() -> None:
    assert is_wallet_billing_enabled() is False


def test_check_wallet_skips_byok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILLING_WALLET_ENABLED", "1")
    import asyncio

    async def _run() -> bool:
        return await check_wallet_allows("acme", 999.0, "byok")

    assert asyncio.run(_run()) is True


def test_wallet_recharge_api(monkeypatch: pytest.MonkeyPatch, tenant_admin: TenantContext) -> None:
    monkeypatch.setattr(
        billing_mod,
        "recharge_wallet",
        lambda **kw: {
            "tenant_id": kw["tenant_id"],
            "amount": kw["amount"],
            "balance_after": 100.0,
            "reference_no": kw["reference_no"],
            "method": kw.get("method", "manual"),
        },
    )
    app = FastAPI()
    app.include_router(billing_router, prefix="/api")

    async def _auth() -> TenantContext:
        return tenant_admin

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    r = TestClient(app).post(
        "/api/billing/wallet/recharge",
        json={"amount": 100, "reference_no": "TX-001"},
    )
    assert r.status_code == 200
    assert r.json()["balance_after"] == 100.0


def test_wallet_get_api(monkeypatch: pytest.MonkeyPatch, tenant_admin: TenantContext) -> None:
    monkeypatch.setattr(
        billing_mod,
        "get_wallet_summary",
        lambda tid, **kw: {
            "tenant_id": tid,
            "balance": 42.5,
            "currency": "CNY",
            "updated_at": None,
            "transactions": [],
        },
    )
    app = FastAPI()
    app.include_router(billing_router, prefix="/api")

    async def _auth() -> TenantContext:
        return tenant_admin

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    r = TestClient(app).get("/api/billing/wallet")
    assert r.status_code == 200
    assert r.json()["balance"] == 42.5


def test_wallet_recharge_deduct_and_insufficient(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILLING_WALLET_ENABLED", "1")
    tid = f"tw_{uuid.uuid4().hex[:10]}"
    recharge_wallet(
        tenant_id=tid,
        amount=10.0,
        reference_no=f"ref-{uuid.uuid4().hex[:6]}",
        operator="tester",
    )
    assert get_balance_sync(tid) == 10.0

    from backend.database.pgvector_session import get_pg_session

    sf = get_pg_session()
    with sf.Session() as session:
        after = deduct_balance_in_session(
            session,
            tenant_id=tid,
            amount=3.5,
            reference_no=f"use-{uuid.uuid4().hex[:6]}",
        )
        session.commit()
    assert after == 6.5
    assert get_balance_sync(tid) == 6.5

    with sf.Session() as session:
        with pytest.raises(InsufficientBalanceError):
            deduct_balance_in_session(
                session,
                tenant_id=tid,
                amount=99.0,
                reference_no=f"use-{uuid.uuid4().hex[:6]}",
            )


def test_concurrent_deduct_cannot_overdraw(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILLING_WALLET_ENABLED", "1")
    tid = f"tw_{uuid.uuid4().hex[:10]}"
    recharge_wallet(
        tenant_id=tid,
        amount=1.0,
        reference_no=f"ref-{uuid.uuid4().hex[:6]}",
        operator="tester",
    )

    from backend.database.pgvector_session import get_pg_session

    sf = get_pg_session()
    failures: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            with sf.Session() as session:
                deduct_balance_in_session(
                    session,
                    tenant_id=tid,
                    amount=0.7,
                    reference_no=f"c-{uuid.uuid4().hex}",
                )
                session.commit()
        except InsufficientBalanceError:
            with lock:
                failures.append("insufficient")

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert failures
    assert get_balance_sync(tid) >= 0.0
    assert get_balance_sync(tid) < 1.0


@pytest.mark.asyncio
async def test_harness_blocks_insufficient_wallet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILLING_WALLET_ENABLED", "1")

    async def _deny(*_a, **_k) -> bool:
        return False

    monkeypatch.setattr(
        "backend.core.harness.llm.get_llm_provider",
        lambda: "openai",
    )
    monkeypatch.setattr("backend.core.billing.wallet.check_wallet_allows", _deny)
    bind_billing_context(user_id="u1", trace_id="tr1", credential_kind="company")
    result = await LLMHarness().generate(
        model="gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        tenant_id="acme",
    )
    assert result.success is False
    assert result.error == "BILLING_003"
