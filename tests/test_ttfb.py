"""Task 71 slice 4 — TTFB gate (mock stream; no live LLM)."""

from __future__ import annotations

import time

import pytest

from packages.pipeline.nodes.task_plan import should_async_plan_on_stream
from packages.pipeline.state import make_initial_state


def test_default_stream_skips_async_plan_for_ttfb(monkeypatch: pytest.MonkeyPatch) -> None:
    """简单闲聊默认不进异步规划（首 token 不被 PlanIR 阻塞）。"""
    monkeypatch.delenv("ASYNC_TASK_PLAN_ON_STREAM", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_ENABLED", raising=False)
    monkeypatch.delenv("FORCE_TASK_PLAN_ON_STREAM", raising=False)

    state = make_initial_state("t", "u", "s", "谢谢")
    state["stream_mode"] = True
    state["intent"] = "conversation"
    state["intent_confidence"] = 0.9
    assert should_async_plan_on_stream(state) is False


def test_orchestrator_on_does_not_wait_8s_plan_before_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """编排开关只跑已有 PlanIR；简单流式消息仍不卡规划 LLM。"""
    monkeypatch.delenv("ASYNC_TASK_PLAN_ON_STREAM", raising=False)
    monkeypatch.delenv("FORCE_TASK_PLAN_ON_STREAM", raising=False)
    monkeypatch.setenv("ORCHESTRATOR_ENABLED", "true")

    state = make_initial_state("t", "u", "s", "谢谢")
    state["stream_mode"] = True
    state["intent"] = "conversation"
    state["intent_confidence"] = 0.9
    assert should_async_plan_on_stream(state) is False


def test_short_path_never_async_plans(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.skills.registry import registry

    registry.load()
    monkeypatch.setenv("ASYNC_TASK_PLAN_ON_STREAM", "1")
    state = make_initial_state("t", "u", "s", "你好")
    state["stream_mode"] = True
    state["intent"] = "greeting"
    state["intent_confidence"] = 0.95
    assert should_async_plan_on_stream(state) is False


@pytest.mark.asyncio
async def test_mock_first_frame_pending_under_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """复杂路径：pending 事件本身应瞬间可发（不计入规划 LLM）。"""
    from packages.plan.event_bus import get_run_bus

    monkeypatch.setenv("ASYNC_TASK_PLAN_ON_STREAM", "1")
    bus = get_run_bus("tr-ttfb")
    t0 = time.perf_counter()
    bus.publish_task_plan_pending(message="planning")
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.05
    assert bus.events_all()[-1].type == "task_plan_pending"
