"""Task 71 slice 3 — memory context acceptance (depends Task 69)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from packages.guardrails.output_guard import check_role_drift
from packages.memory.memory_service import MEMORY_ISOLATION_HEADER
from packages.pipeline.context_messages import build_llm_messages, expand_hot_messages
from packages.pipeline.nodes import load_memory as lm
from packages.pipeline.state import make_initial_state


def test_multi_turn_history_expanded_as_roles() -> None:
    state = make_initial_state("t", "u", "s", "我叫什么")
    state["hot_memory"] = [
        {"role": "user", "content": "我叫小明"},
        {"role": "assistant", "content": "好的，小明"},
        {"role": "user", "content": "我做电商"},
        {"role": "assistant", "content": "了解"},
        {"role": "user", "content": "随便聊聊"},
        {"role": "assistant", "content": "嗯"},
    ]
    msgs = build_llm_messages(state, system_template="你是助手")
    roles = [m["role"] for m in msgs]
    assert roles.count("user") >= 3
    assert roles.count("assistant") >= 2
    assert msgs[-1]["content"] == "我叫什么"


@pytest.mark.asyncio
async def test_load_memory_passes_session_id(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    class _Svc:
        async def read(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(
                hot=[],
                warm={},
                cold=[],
                warm_meta={},
            )

    monkeypatch.setattr(lm, "get_unified_memory_service", lambda **_k: _Svc())
    state = make_initial_state("t1", "u1", "sess-A", "hi")
    await lm.load_memory(state)
    assert seen.get("session_id") == "sess-A"


def test_budget_trim_many_turns_no_error() -> None:
    hot = []
    for i in range(20):
        hot.append({"role": "user", "content": f"u{i} " + ("x" * 200)})
        hot.append({"role": "assistant", "content": f"a{i} " + ("y" * 200)})
    out = expand_hot_messages(hot, max_turns=10, budget_tokens=800)
    assert len(out) <= 20
    assert out[-1]["role"] in ("user", "assistant")


@pytest.mark.asyncio
async def test_role_drift_blocks_persona_collapse() -> None:
    """恶意/漂移记忆内容应被 check_role_drift 拦截；隔离头可保留在 prompt block。"""
    malicious = "家人们，点击直播间下单"
    result = await check_role_drift(malicious)
    assert result.action == "blocked"

    state = make_initial_state("t", "u", "s", "hi")
    state["memory_prompt_block"] = MEMORY_ISOLATION_HEADER + "\n[用户背景]\n- note: x"
    msgs = build_llm_messages(state, system_template="助手")
    assert MEMORY_ISOLATION_HEADER not in msgs[0]["content"]
    assert MEMORY_ISOLATION_HEADER in msgs[-1]["content"]
