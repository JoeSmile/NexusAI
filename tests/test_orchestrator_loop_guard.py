"""Task 62 — orchestrator loop-guard integration."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from packages.plan.loop_guard import LoopGuardError
from packages.plan.models import PlanIR, PlanStep
from packages.plan.spawn_budget import SpawnBudget
from packages.pipeline.nodes.orchestrator import OrchestratorError, execute_plan_ir
from packages.pipeline.state import make_initial_state


def _state():
    state = make_initial_state("t1", "u1", "s1", "hello")
    state["user_context"] = {
        "tenant_id": "t1",
        "user_id": "u1",
        "role": "user",
        "permissions": ["chat:write"],
        "is_cross_tenant": False,
    }
    return state


@pytest.mark.asyncio
async def test_execute_plan_loop_guard_stops_on_dup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOOP_GUARD_MAX_DUP_STREAK", "3")
    monkeypatch.setenv("LOOP_GUARD_SESSION_CAP", "50")
    state = _state()
    plan = PlanIR(
        goal="p",
        steps=[
            PlanStep(id="s1", capability_id="cap.a", params={"x": 1}),
            PlanStep(id="s2", capability_id="cap.a", params={"x": 1}),
            PlanStep(id="s3", capability_id="cap.a", params={"x": 1}),
        ],
        version=1,
    )
    calls = 0

    async def fake_collect(cap_id, payload, tenant):
        nonlocal calls
        calls += 1
        return {
            "ok": True,
            "output": cap_id,
            "text": cap_id,
            "capability_id": cap_id,
        }

    monkeypatch.setattr(
        "packages.pipeline.nodes.orchestrator._collect_invoke",
        fake_collect,
    )
    monkeypatch.setattr(
        "packages.pipeline.nodes.orchestrator._list_visible_capabilities",
        lambda s: [{"id": "cap.a", "param_spec": {}}],
    )

    audits: list[dict] = []
    with patch(
        "packages.plan.loop_guard.write_audit_sync",
        side_effect=lambda r: audits.append(r) or True,
    ):
        with pytest.raises(OrchestratorError, match="重复执行"):
            await execute_plan_ir(
                state,
                plan,
                budget=SpawnBudget(max_workers=1, max_depth=1, max_spawn_total=32),
            )

    assert calls == 2
    assert state.get("finish_reason") == "loop_guard"
    assert any(a.get("action") == "orchestrator.loop_guard" for a in audits)
