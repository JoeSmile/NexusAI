"""Task 69 — memory/history injection into LLM messages."""

from __future__ import annotations

import pytest

from packages.memory.memory_service import MEMORY_ISOLATION_HEADER
from packages.prompt_service import DEFAULT_CHAT_SYSTEM, render_prompt
from packages.pipeline.context_messages import (
    build_llm_messages,
    current_user_content,
    expand_hot_messages,
)
from packages.pipeline.nodes import load_memory as lm
from packages.pipeline.nodes import llm_generate as lg
from packages.pipeline.state import make_initial_state


def test_render_prompt_whitelist_only() -> None:
    tpl = "Hi {role}\n{memory}\n{history}\n{evil}"
    out = render_prompt(tpl, {"role": "助手", "memory": "M", "history": "H"})
    assert "助手" in out
    assert "M" in out
    assert "H" in out
    assert "{evil}" in out


def test_expand_hot_messages_trims_oldest() -> None:
    hot = [
        {"role": "user", "content": "a" * 2000},
        {"role": "assistant", "content": "b" * 2000},
        {"role": "user", "content": "recent"},
    ]
    out = expand_hot_messages(hot, max_turns=10, budget_tokens=600)
    assert out[-1]["content"] == "recent"
    assert len(out) < len(hot)


def test_build_llm_messages_appends_memory_without_placeholder() -> None:
    state = make_initial_state("t1", "u1", "s1", "问")
    state["memory_prompt_block"] = "[用户背景]\n- identity:name: 小明"
    msgs = build_llm_messages(state, system_template="你是助手。")
    assert "小明" in msgs[0]["content"]


def test_build_llm_messages_injects_memory_and_hot() -> None:
    state = make_initial_state("t1", "u1", "s1", "我叫小明")
    state["memory_prompt_block"] = MEMORY_ISOLATION_HEADER + "\n[用户背景]\n- identity:name: 小明"
    state["hot_memory"] = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，有什么可以帮你？"},
    ]
    state["assembled_prompt"] = "user: 我叫小明"
    msgs = build_llm_messages(state, system_template=DEFAULT_CHAT_SYSTEM)
    assert msgs[0]["role"] == "system"
    assert "小明" in msgs[0]["content"]
    assert msgs[1]["role"] == "user"
    assert msgs[2]["role"] == "assistant"
    assert msgs[-1] == {"role": "user", "content": "我叫小明"}


@pytest.mark.asyncio
async def test_llm_generate_uses_multi_turn_messages(monkeypatch) -> None:
    captured: dict = {}

    class _H:
        async def generate(self, **kwargs):
            captured.update(kwargs)
            from types import SimpleNamespace

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
        from types import SimpleNamespace

        return SimpleNamespace(
            content=DEFAULT_CHAT_SYSTEM,
            name="chat.system",
            version=1,
            label="production",
            source="test",
        )

    monkeypatch.setattr(lg.asyncio, "to_thread", _to_thread)
    state = make_initial_state("t1", "u1", "s1", "当前问题")
    state["selected_model"] = "deepseek-v4-flash"
    state["memory_prompt_block"] = MEMORY_ISOLATION_HEADER
    state["hot_memory"] = [{"role": "user", "content": "历史"}]
    state["assembled_prompt"] = "user: 当前问题"
    await lg.llm_generate(state)
    messages = captured.get("messages") or []
    assert messages[0]["role"] == "system"
    assert any(m.get("content") == "历史" for m in messages)
    assert messages[-1]["content"] == "当前问题"


@pytest.mark.asyncio
async def test_load_memory_passes_session_id(monkeypatch) -> None:
    seen: dict = {}

    class _Svc:
        async def read(self, **kwargs):
            seen.update(kwargs)
            from packages.memory.memory_service import MemoryBundle

            return MemoryBundle(hot=[{"role": "user", "content": "hi"}])

    monkeypatch.setattr(
        lm,
        "get_unified_memory_service",
        lambda **_k: _Svc(),
    )
    state = make_initial_state("t1", "u1", "session-abc", "hello")
    out = await lm.load_memory(state)
    assert seen.get("session_id") == "session-abc"
    assert seen.get("hot_limit") == 10
    assert out["hot_memory"][0]["content"] == "hi"


@pytest.mark.asyncio
async def test_build_context_splits_memory_and_user() -> None:
    from packages.pipeline.nodes.build_context import build_context

    state = make_initial_state("t1", "u1", "s1", "你好")
    state["warm_memory"] = {"identity:name": "小明"}
    state["hot_memory"] = [{"role": "user", "content": "上一轮"}]
    out = await build_context(state)
    assert MEMORY_ISOLATION_HEADER in (out.get("memory_prompt_block") or "")
    assert "小明" in (out.get("memory_prompt_block") or "")
    assert "上一轮" not in (out.get("memory_prompt_block") or "")
    assert current_user_content(out) == "你好"
