"""Task 72 D7 — finish_reason in SSE done frame."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.fallback import get_fallback
from packages.harness.llm import LLMHarness
from packages.pipeline.router import _sse_done_payload


def test_sse_done_payload_includes_finish_reason():
    payload = _sse_done_payload(
        {
            "finish_reason": "fallback",
            "trace_id": "tr-1",
            "response": "hi",
        }
    )
    assert payload["type"] == "done"
    assert payload["finish_reason"] == "fallback"
    assert payload["trace_id"] == "tr-1"


def test_sse_done_payload_defaults_llm_generated():
    payload = _sse_done_payload({"trace_id": "t2"})
    assert payload["finish_reason"] == "llm_generated"


def test_sse_done_payload_serializable():
    payload = _sse_done_payload({"finish_reason": "fallback", "trace_id": "x"})
    raw = json.dumps(payload, ensure_ascii=False)
    assert "fallback" in raw


@pytest.mark.asyncio
async def test_harness_stream_finish_reason_fallback(monkeypatch):
    harness = LLMHarness()

    async def _fail(**kwargs):
        if False:
            yield ""
        raise RuntimeError("exhausted")

    monkeypatch.setattr(harness, "_stream_with_resilience", _fail)
    monkeypatch.setattr("packages.harness.llm.get_llm_provider", lambda: "openai")
    monkeypatch.setattr("packages.harness.llm._terms_allows", AsyncMock(return_value=True))
    monkeypatch.setattr("packages.harness.llm._wallet_allows", AsyncMock(return_value=True))
    monkeypatch.setattr("packages.harness.llm._budget_allows", AsyncMock(return_value=True))
    monkeypatch.setattr("packages.harness.llm.record_consumption", lambda *a, **k: None)

    chunks: list[str] = []
    async for ch in harness._stream_unlocked(
        "m1",
        [{"role": "user", "content": "hi"}],
        tenant_id="t1",
    ):
        chunks.append(ch)

    assert "".join(chunks) == get_fallback("zh")
    assert harness.stream_finish_reason() == "fallback"


@pytest.mark.asyncio
async def test_llm_generate_finish_reason_fallback(monkeypatch):
    from packages.pipeline.nodes import llm_generate as lg
    from packages.pipeline.state import make_initial_state

    class _H:
        async def generate(self, **kwargs):
            return MagicMock(
                success=False,
                output="",
                latency_ms=1.0,
                error="LLM_002",
                metadata={},
            )

    monkeypatch.setattr(lg, "harness", _H())
    monkeypatch.setattr(
        lg,
        "_resolve_system_template",
        AsyncMock(return_value=("sys", {})),
    )
    monkeypatch.setattr(
        lg,
        "build_llm_messages",
        lambda s, **k: [{"role": "user", "content": "hi"}],
    )

    state = make_initial_state("t1", "u1", "s1", "hi")
    state["selected_model"] = "deepseek-v4-flash"
    state["llm_api_key"] = "k"
    state["llm_base_url"] = "https://api.example/v1"
    state["finish_reason"] = "routed_to_llm"

    out = await lg.llm_generate(state)
    assert out["finish_reason"] == "fallback"
    assert out["response"] == get_fallback("zh")
