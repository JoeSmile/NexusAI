"""Task 72 slice 1 — Token TPM/TPD quota."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import backend.core.token_quota as tq
from backend.core.errors import NexusAIException
from packages.pipeline.nodes import rate_limiter as rl_mod


@pytest.fixture(autouse=True)
def _clear_env_limits(monkeypatch):
    monkeypatch.delenv("TOKEN_QUOTA_TPM", raising=False)
    monkeypatch.delenv("TOKEN_QUOTA_TPD", raising=False)
    monkeypatch.setenv("TOKEN_QUOTA_TPM", "0")
    monkeypatch.setenv("TOKEN_QUOTA_TPD", "0")


def test_estimate_request_tokens_includes_history_and_max_output(monkeypatch):
    monkeypatch.setenv("TOKEN_QUOTA_DEFAULT_MAX_OUTPUT", "500")
    state = {
        "message": "hello",
        "hot_memory": [{"role": "user", "content": "prev"}],
        "warm_memory": {"k": "warm snippet"},
    }
    est = tq.estimate_request_tokens(state)
    assert est > 500


def test_check_token_quota_redis_down_passes(monkeypatch):
    monkeypatch.setenv("TOKEN_QUOTA_TPM", "100")
    monkeypatch.setattr(tq, "_redis", lambda: None)
    assert tq.check_token_quota("t1", 9999) is True


def test_tpm_limit_blocks_second_request(monkeypatch):
    monkeypatch.setenv("TOKEN_QUOTA_TPM", "1000")
    monkeypatch.setenv("TOKEN_QUOTA_TPD", "0")
    store: dict[str, int] = {}

    class _Redis:
        def get(self, key):
            return str(store.get(key, 0))

        def incrby(self, key, n):
            store[key] = int(store.get(key, 0)) + int(n)
            return store[key]

        def expire(self, key, ttl):
            return True

    monkeypatch.setattr(tq, "_redis", lambda: _Redis())
    monkeypatch.setattr(tq, "estimate_request_tokens", lambda state: 600)

    assert tq.check_token_quota("t1", 600) is True
    tq.record_token_usage("t1", 600)
    assert tq.check_token_quota("t1", 600) is False


def test_record_token_usage_uses_tq_keys_not_cap(monkeypatch):
    monkeypatch.setenv("TOKEN_QUOTA_TPM", "5000")
    keys_touched: list[str] = []

    class _Redis:
        def incrby(self, key, n):
            keys_touched.append(key)
            return int(n)

        def expire(self, key, ttl):
            return True

    monkeypatch.setattr(tq, "_redis", lambda: _Redis())
    tq.record_token_usage("tenant-a", 42)
    assert keys_touched
    assert all(k.startswith("tq:tpm:tenant-a:") for k in keys_touched)
    assert not any(k.startswith("rl:cap:") for k in keys_touched)


@pytest.mark.asyncio
async def test_rate_limiter_token_quota_raises(monkeypatch):
    monkeypatch.setattr(rl_mod, "check_rate_limit", lambda tid: True)
    monkeypatch.setattr(rl_mod, "estimate_request_tokens", lambda state: 800)
    monkeypatch.setattr(rl_mod, "check_token_quota", lambda tid, est: False)

    state = {
        "tenant_id": "t1",
        "message": "hi",
    }
    with pytest.raises(NexusAIException) as ei:
        await rl_mod.rate_limiter(state)
    assert ei.value.code == "RATE_001"


@pytest.mark.asyncio
async def test_rate_limiter_passes_when_quota_disabled(monkeypatch):
    monkeypatch.setattr(rl_mod, "check_rate_limit", lambda tid: True)
    monkeypatch.setattr(rl_mod, "estimate_request_tokens", lambda state: 100)
    monkeypatch.setattr(rl_mod, "check_token_quota", lambda tid, est: True)

    state = {"tenant_id": "t1", "message": "hi"}
    out = await rl_mod.rate_limiter(state)
    assert out is state
