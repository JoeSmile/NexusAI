"""Chat UI prefs (temperature / max_tokens) reach the LLM harness."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.pipeline.nodes import llm_generate as lg
from backend.pipeline.state import make_initial_state


@pytest.mark.asyncio
async def test_llm_generate_passes_temperature_and_max_tokens(monkeypatch) -> None:
    captured: dict = {}

    class _H:
        async def generate(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                success=True,
                output="ok",
                latency_ms=1.0,
                error=None,
                metadata={"input_tokens": 1, "output_tokens": 1, "cost": 0.0},
            )

    monkeypatch.setattr(lg, "harness", _H())
    monkeypatch.setattr(lg, "enrich_span", lambda **_k: None)
    monkeypatch.setattr(lg, "resolve_prompt_label", lambda **_k: "production")

    async def _to_thread(_fn, *_a, **_k):
        return SimpleNamespace(
            content="sys",
            name="chat.system",
            version=1,
            label="production",
            source="test",
        )

    monkeypatch.setattr(lg.asyncio, "to_thread", _to_thread)
    state = make_initial_state(
        "t1",
        "u1",
        "s1",
        "hi",
        llm_temperature=0.3,
        llm_max_tokens=512,
    )
    state["selected_model"] = "deepseek-v4-flash"
    state["finish_reason"] = "routed_to_llm"
    await lg.llm_generate(state)
    assert captured.get("temperature") == 0.3
    assert captured.get("max_tokens") == 512


def test_completion_kwargs_omits_max_tokens_when_unset() -> None:
    from backend.core.harness.llm import _completion_kwargs

    p = _completion_kwargs(
        model="m",
        messages=[{"role": "user", "content": "x"}],
        temperature=0.3,
        max_tokens=None,
        stream=True,
    )
    assert p["temperature"] == 0.3
    assert p["stream"] is True
    assert "max_tokens" not in p
