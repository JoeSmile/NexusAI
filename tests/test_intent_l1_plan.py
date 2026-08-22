"""Task 64 slice 2 — L1 sub-task intent via PlanIR steps."""

from __future__ import annotations

import pytest

from backend.core.auth.models import TenantContext
from backend.core.plan.models import PlanIR, PlanStep
from backend.core.plan.validator import validate_plan_ir
from backend.pipeline.nodes.orchestrator import _run_step_once
from backend.pipeline.state import make_initial_state


def _caps() -> dict[str, dict]:
    return {
        "hotspot.dig": {"param_spec": {}},
        "script.gen": {"param_spec": {}},
    }


def test_plan_step_sub_query_validates():
    plan = validate_plan_ir(
        {
            "goal": "复合任务",
            "version": 1,
            "steps": [
                {
                    "id": "dig",
                    "capability_id": "hotspot.dig",
                    "sub_query": "抓取专升本热点",
                    "params": {},
                },
                {
                    "id": "script",
                    "capability_id": "script.gen",
                    "sub_query": "为热点写口播",
                    "depends_on": ["dig"],
                    "params": {},
                },
            ],
        },
        caps_by_id=_caps(),
    )
    assert plan.steps[0].sub_query == "抓取专升本热点"
    assert plan.steps[1].capability_id == "script.gen"


@pytest.mark.asyncio
async def test_sub_query_merged_into_invoke_payload(monkeypatch):
    captured: list[dict] = []

    async def fake_collect(cap_id, payload, tenant):
        captured.append(payload)
        return {"ok": True, "output": "ok", "text": "ok", "capability_id": cap_id}

    monkeypatch.setattr(
        "backend.pipeline.nodes.orchestrator._collect_invoke",
        fake_collect,
    )
    step = PlanStep(
        id="s1",
        capability_id="hotspot.dig",
        sub_query="今日考研热点",
        params={},
    )
    state = make_initial_state("t1", "u1", "s1", "hello")
    tenant = TenantContext("t1", "u1", "user", ["chat:write"], False)
    await _run_step_once(step, step_results={}, tenant=tenant, state=state)
    assert captured[0].get("message") == "今日考研热点"
