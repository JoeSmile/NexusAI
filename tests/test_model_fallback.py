"""Task 72 — chat path model fallback chain."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import packages.harness.llm as llm_mod
import backend.core.key_failover as key_failover
from packages.harness.llm import LLMHarness
from backend.core.key_repository import LLMKey
from backend.core.model_registry import fallback_chain, reload_registry


class _APIStatusError(Exception):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(str(status_code))


@pytest.fixture(autouse=True)
def _reload_models(monkeypatch):
    monkeypatch.delenv("MODEL_REGISTRY_JSON", raising=False)
    monkeypatch.setenv("MODEL_CHEAP", "cheap-model")
    monkeypatch.setenv("MODEL_GOOD", "good-model")
    monkeypatch.setenv("MODEL_BEST", "best-model")
    reload_registry()


def test_fallback_chain_deescalates():
    from backend.core.model_registry import _TIER_RANK, get_model

    chain = fallback_chain("best-model")
    assert "best-model" not in chain
    assert chain
    base_rank = _TIER_RANK["best"]
    for name in chain:
        spec = get_model(name)
        assert spec is not None
        assert _TIER_RANK[spec.tier] < base_rank


def test_classify_model_fallback_500():
    assert key_failover.classify_model_fallback_status(_APIStatusError(500)) is True
    assert key_failover.classify_model_fallback_status(_APIStatusError(429)) is False
    assert key_failover.should_try_next_model(_APIStatusError(503)) is True


@pytest.mark.asyncio
async def test_call_api_switches_model_on_500(monkeypatch):
    harness = LLMHarness()
    calls: list[str] = []

    async def _fake_keys(tenant_id, model, *, api_key, base_url, key_provider, allow_pipeline):
        return [
            LLMKey(
                str(model),
                tenant_id,
                "chat",
                "https://api.example/v1",
                "key",
                1,
                True,
                None,
            )
        ]

    async def _fake_failover(chain, call_fn, *, repo, tenant_id, provider):
        m = chain[0].id
        calls.append(m)
        if m == "best-model":
            raise _APIStatusError(500)
        return "ok-from-good"

    monkeypatch.setattr(llm_mod, "_keys_for_model", _fake_keys)
    monkeypatch.setattr(key_failover, "call_with_key_failover", _fake_failover)

    out = await harness._call_api(
        "best-model",
        [{"role": "user", "content": "hi"}],
        tenant_id="t1",
        key_provider="chat",
    )
    assert out == "ok-from-good"
    assert calls[0] == "best-model"
    assert len(calls) == 2
    assert calls[1] != "best-model"


@pytest.mark.asyncio
async def test_stream_does_not_call_generate_on_failure(monkeypatch):
    harness = LLMHarness()
    generate_called = False

    async def _fake_gen(*a, **k):
        nonlocal generate_called
        generate_called = True
        raise AssertionError("stream must not fall back to generate")

    async def _fail_stream(**kwargs):
        if False:
            yield ""
        raise _APIStatusError(500)

    monkeypatch.setattr(harness, "generate", _fake_gen)
    monkeypatch.setattr(harness, "_stream_with_resilience", _fail_stream)
    monkeypatch.setattr(llm_mod, "get_llm_provider", lambda: "openai")
    monkeypatch.setattr(llm_mod, "_terms_allows", AsyncMock(return_value=True))
    monkeypatch.setattr(llm_mod, "_wallet_allows", AsyncMock(return_value=True))
    monkeypatch.setattr(llm_mod, "_budget_allows", AsyncMock(return_value=True))

    chunks: list[str] = []
    async for ch in harness._stream_unlocked(
        "best-model",
        [{"role": "user", "content": "hi"}],
        tenant_id="t1",
        api_key="k",
        base_url="https://api.example/v1",
    ):
        chunks.append(ch)

    assert generate_called is False
    assert "".join(chunks)  # static fallback text


@pytest.mark.asyncio
async def test_keys_for_model_skips_model_without_credential(monkeypatch):
    async def _chain(tenant_id, model, limit=3):
        if model == "good-model":
            return [
                LLMKey("10", tenant_id, "chat", "https://g", "k", 1, True, None),
            ]
        return []

    monkeypatch.setattr(
        "backend.core.llm_credentials.get_key_chain_for_model",
        _chain,
    )

    keys = await llm_mod._keys_for_model(
        "t1",
        "good-model",
        api_key=None,
        base_url=None,
        key_provider="chat",
        allow_pipeline=False,
    )
    assert len(keys) == 1

    empty = await llm_mod._keys_for_model(
        "t1",
        "missing-model",
        api_key=None,
        base_url=None,
        key_provider="chat",
        allow_pipeline=False,
    )
    assert empty == []
