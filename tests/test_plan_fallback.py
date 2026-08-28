"""Task 71 slice 4 — plan async timeout degrade (depends Task 70)."""

from __future__ import annotations

import asyncio

import pytest

from packages.plan.event_bus import get_run_bus
from packages.pipeline.nodes.task_plan import run_async_task_plan_for_stream
from packages.pipeline.state import make_initial_state


@pytest.mark.asyncio
async def test_plan_timeout_degrades_to_direct_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASYNC_TASK_PLAN_ON_STREAM", "1")
    monkeypatch.delenv("ORCHESTRATOR_ENABLED", raising=False)
    monkeypatch.delenv("FORCE_TASK_PLAN_ON_STREAM", raising=False)

    async def slow(_state):
        await asyncio.sleep(1.0)
        return {"goal": "late"}

    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan._produce_plan_ir", slow
    )
    monkeypatch.setattr(
        "packages.pipeline.intent_path.registry.get_skill_for_intent",
        lambda *a, **k: None,
    )

    state = make_initial_state("t", "u", "s", "complex multi step")
    state["stream_mode"] = True
    state["intent"] = "complex"
    state["intent_confidence"] = 0.2
    state["trace_id"] = "tr-plan-fallback"
    bus = get_run_bus("tr-plan-fallback")

    out, status = await run_async_task_plan_for_stream(
        state, timeout_s=0.05, emit_pending=True
    )
    assert status == "timeout"
    assert out.get("task_plan") is None
    # 仍可走直答：finish_reason 保持 routed_to_llm 或未改成 error
    assert out.get("finish_reason") in (None, "routed_to_llm", "")
    done = [e for e in bus.events_all() if e.type == "task_plan_done"]
    assert done and done[-1].payload.get("status") == "timeout"
