"""Task 71 slice 4 — TTFB gate (mock stream; no live LLM)."""

from __future__ import annotations

import time

import pytest

from backend.pipeline.nodes.task_plan import should_async_plan_on_stream
from backend.pipeline.state import make_initial_state


def test_default_stream_skips_async_plan_for_ttfb(monkeypatch: pytest.MonkeyPatch) -> None:
    """FORCE/ASYNC 均关时，不应进入异步规划等待（首 token 不被 PlanIR 阻塞）。"""
    monkeypatch.delenv("ASYNC_TASK_PLAN_ON_STREAM", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_ENABLED", raising=False)
    monkeypatch.delenv("FORCE_TASK_PLAN_ON_STREAM", raising=False)

    state = make_initial_state("t", "u", "s", "帮我写周报")
    state["stream_mode"] = True
    state["intent"] = "content_creation"
    state["intent_confidence"] = 0.5
    assert should_async_plan_on_stream(state) is False


def test_short_path_never_async_plans(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.skills.registry import registry

    registry.discover()
    monkeypatch.setenv("ASYNC_TASK_PLAN_ON_STREAM", "1")
    state = make_initial_state("t", "u", "s", "你好")
    state["stream_mode"] = True
    state["intent"] = "greeting"
    state["intent_confidence"] = 0.95
    assert should_async_plan_on_stream(state) is False


@pytest.mark.asyncio
async def test_mock_first_frame_pending_under_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """复杂路径：pending 事件本身应瞬间可发（不计入规划 LLM）。"""
    from backend.core.plan.event_bus import get_run_bus

    monkeypatch.setenv("ASYNC_TASK_PLAN_ON_STREAM", "1")
    bus = get_run_bus("tr-ttfb")
    t0 = time.perf_counter()
    bus.publish_task_plan_pending(message="planning")
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.05
    assert bus.events_all()[-1].type == "task_plan_pending"
