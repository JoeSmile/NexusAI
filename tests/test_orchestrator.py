"""Task 56 切片 3 — orchestrator 执行器。"""

from __future__ import annotations

import pytest

from backend.core.plan.models import OnFailMode, PlanIR, PlanStep, PlanStepRetry
from backend.core.plan.spawn_budget import SpawnBudget
from backend.pipeline.nodes.orchestrator import (
    OrchestratorError,
    execute_plan_ir,
    orchestrator,
    should_run_orchestrator,
)
from backend.pipeline.state import make_initial_state


def _plan_two_parallel() -> PlanIR:
    return PlanIR(
        goal="test",
        steps=[
            PlanStep(id="s1", capability_id="cap.a", params={}),
            PlanStep(id="s2", capability_id="cap.b", params={}),
            PlanStep(
                id="s3",
                capability_id="cap.c",
                params={"source_step": "s1"},
                depends_on=["s1"],
            ),
        ],
        version=1,
    )


def _state_with_plan(plan: PlanIR | None = None):
    state = make_initial_state("t1", "u1", "s1", "hello")
    state["user_context"] = {
        "tenant_id": "t1",
        "user_id": "u1",
        "role": "user",
        "permissions": ["chat:write"],
        "is_cross_tenant": False,
    }
    if plan is not None:
        state["task_plan"] = plan.model_dump(mode="json")
    return state


def test_should_run_orchestrator_requires_flag_and_plan(monkeypatch):
    state = _state_with_plan(_plan_two_parallel())
    monkeypatch.delenv("ORCHESTRATOR_ENABLED", raising=False)
    assert should_run_orchestrator(state) is False
    monkeypatch.setenv("ORCHESTRATOR_ENABLED", "1")
    assert should_run_orchestrator(state) is True
    state["stream_mode"] = True
    assert should_run_orchestrator(state) is False


@pytest.mark.asyncio
async def test_execute_plan_parallel_steps(monkeypatch):
    state = _state_with_plan()
    plan = PlanIR(
        goal="p",
        steps=[
            PlanStep(id="s1", capability_id="cap.a", params={}),
            PlanStep(id="s2", capability_id="cap.b", params={}),
        ],
        version=1,
    )
    calls: list[str] = []

    async def fake_collect(cap_id, payload, tenant):
        calls.append(cap_id)
        return {"ok": True, "output": cap_id, "text": cap_id, "capability_id": cap_id}

    monkeypatch.setattr(
        "backend.pipeline.nodes.orchestrator._collect_invoke",
        fake_collect,
    )
    monkeypatch.setattr(
        "backend.pipeline.nodes.orchestrator._list_visible_capabilities",
        lambda s: [
            {"id": "cap.a", "param_spec": {}},
            {"id": "cap.b", "param_spec": {}},
        ],
    )

    results, final_plan, spawn_total = await execute_plan_ir(
        state,
        plan,
        budget=SpawnBudget(max_workers=8, max_depth=3, max_spawn_total=32),
    )
    assert set(calls) == {"cap.a", "cap.b"}
    assert results["s1"]["output"] == "cap.a"
    assert spawn_total >= 2
    assert len(final_plan.steps) == 2


@pytest.mark.asyncio
async def test_execute_plan_spawn_budget_serializes(monkeypatch):
    state = _state_with_plan()
    plan = PlanIR(
        goal="p",
        steps=[
            PlanStep(id="s1", capability_id="cap.a", params={}),
            PlanStep(id="s2", capability_id="cap.b", params={}),
        ],
        version=1,
    )
    order: list[str] = []

    async def fake_collect(cap_id, payload, tenant):
        order.append(cap_id)
        return {"ok": True, "output": cap_id, "text": cap_id, "capability_id": cap_id}

    monkeypatch.setattr(
        "backend.pipeline.nodes.orchestrator._collect_invoke",
        fake_collect,
    )
    monkeypatch.setattr(
        "backend.pipeline.nodes.orchestrator._list_visible_capabilities",
        lambda s: [
            {"id": "cap.a", "param_spec": {}},
            {"id": "cap.b", "param_spec": {}},
        ],
    )

    tight = SpawnBudget(max_workers=1, max_depth=1, max_spawn_total=32)
    await execute_plan_ir(state, plan, budget=tight)
    assert len(order) == 2


@pytest.mark.asyncio
async def test_execute_plan_skip_on_fail(monkeypatch):
    state = _state_with_plan()
    plan = PlanIR(
        goal="p",
        steps=[
            PlanStep(
                id="s1",
                capability_id="cap.a",
                params={},
                on_fail=OnFailMode.SKIP,
            ),
        ],
        version=1,
    )

    async def boom(*a, **k):
        raise RuntimeError("fail")

    monkeypatch.setattr("backend.pipeline.nodes.orchestrator._collect_invoke", boom)
    monkeypatch.setattr(
        "backend.pipeline.nodes.orchestrator._list_visible_capabilities",
        lambda s: [{"id": "cap.a", "param_spec": {}}],
    )

    results, _, _ = await execute_plan_ir(state, plan)
    assert results["s1"]["skipped"] is True


@pytest.mark.asyncio
async def test_execute_plan_fail_raises(monkeypatch):
    state = _state_with_plan()
    plan = PlanIR(
        goal="p",
        steps=[PlanStep(id="s1", capability_id="cap.a", params={})],
        version=1,
    )

    async def boom(*a, **k):
        raise RuntimeError("fail")

    monkeypatch.setattr("backend.pipeline.nodes.orchestrator._collect_invoke", boom)
    monkeypatch.setattr(
        "backend.pipeline.nodes.orchestrator._list_visible_capabilities",
        lambda s: [{"id": "cap.a", "param_spec": {}}],
    )

    with pytest.raises(OrchestratorError):
        await execute_plan_ir(state, plan)


@pytest.mark.asyncio
async def test_execute_plan_retry(monkeypatch):
    state = _state_with_plan()
    plan = PlanIR(
        goal="p",
        steps=[
            PlanStep(
                id="s1",
                capability_id="cap.a",
                params={},
                on_fail=OnFailMode.RETRY,
                retry=PlanStepRetry(max=2, backoff_s=0.0),
            ),
        ],
        version=1,
    )
    n = {"v": 0}

    async def flaky(*a, **k):
        n["v"] += 1
        if n["v"] < 3:
            raise RuntimeError("transient")
        return {"ok": True, "output": "ok", "text": "ok", "capability_id": "cap.a"}

    monkeypatch.setattr("backend.pipeline.nodes.orchestrator._collect_invoke", flaky)
    monkeypatch.setattr(
        "backend.pipeline.nodes.orchestrator._list_visible_capabilities",
        lambda s: [{"id": "cap.a", "param_spec": {}}],
    )

    results, _, _ = await execute_plan_ir(state, plan)
    assert results["s1"]["output"] == "ok"
    assert n["v"] == 3


@pytest.mark.asyncio
async def test_orchestrator_node_sets_response(monkeypatch):
    state = _state_with_plan(_plan_two_parallel())
    monkeypatch.setenv("ORCHESTRATOR_ENABLED", "1")

    async def fake_exec(state_in, plan, **kwargs):
        return (
            {"s1": {"output": "a"}, "s2": {"output": "b"}},
            plan,
            2,
        )

    monkeypatch.setattr(
        "backend.pipeline.nodes.orchestrator.execute_plan_ir",
        fake_exec,
    )
    monkeypatch.setattr(
        "backend.pipeline.nodes.orchestrator._caps_index",
        lambda s: {"cap.a": {}, "cap.b": {}, "cap.c": {}},
    )
    monkeypatch.setattr(
        "backend.pipeline.nodes.orchestrator.validate_plan_ir",
        lambda raw, **kw: _plan_two_parallel(),
    )

    out = await orchestrator(state)
    assert out["finish_reason"] == "orchestrated"
    assert "cap.a" in out["response"] or "s1" in out["response"]
