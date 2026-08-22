"""Task 64 slice 1 — L0 intent classification once per message."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.pipeline.cache.fingerprint_cache import make_fingerprint
from backend.pipeline.nodes.analyze_parallel import analyze_parallel
from backend.pipeline.nodes.orchestrator import execute_plan_ir
from backend.pipeline.state import make_initial_state
from backend.core.plan.models import PlanIR, PlanStep


@pytest.mark.asyncio
async def test_analyze_parallel_calls_detect_intent_once(monkeypatch):
    calls: list[str] = []

    def fake_detect(self, text: str):
        calls.append(text)
        result = MagicMock()
        result.intent = MagicMock(value="greeting")
        result.confidence = 0.92
        result.source = "rule"
        return result

    monkeypatch.setattr(
        "backend.modules.intent.core.intent_classifier.IntentClassifier.detect_intent",
        fake_detect,
    )
    state = make_initial_state("t1", "u1", "s1", "你好呀")
    out = await analyze_parallel(state)
    assert len(calls) == 1
    assert calls[0] == "你好呀"
    assert out["intent"] == "greeting"
    assert out["fingerprint"] == make_fingerprint("greeting", {})


@pytest.mark.asyncio
async def test_orchestrator_execution_does_not_reclassify_l0(monkeypatch):
    detect_calls: list[str] = []

    def fake_detect(self, text: str):
        detect_calls.append(text)
        result = MagicMock()
        result.intent = MagicMock(value="function")
        result.confidence = 0.8
        result.source = "model"
        return result

    monkeypatch.setattr(
        "backend.modules.intent.core.intent_classifier.IntentClassifier.detect_intent",
        fake_detect,
    )

    state = make_initial_state("t1", "u1", "s1", "帮我抓热点")
    await analyze_parallel(state)
    assert len(detect_calls) == 1

    plan = PlanIR(
        goal="dig",
        steps=[
            PlanStep(id="s1", capability_id="cap.a", params={}),
            PlanStep(id="s2", capability_id="cap.b", params={}, depends_on=["s1"]),
        ],
        version=1,
    )
    state["user_context"] = {
        "tenant_id": "t1",
        "user_id": "u1",
        "role": "user",
        "permissions": ["chat:write"],
    }

    async def fake_collect(cap_id, payload, tenant):
        return {
            "ok": True,
            "output": cap_id,
            "text": cap_id,
            "capability_id": cap_id,
        }

    monkeypatch.setattr(
        "backend.pipeline.nodes.orchestrator._collect_invoke",
        fake_collect,
    )
    await execute_plan_ir(state, plan)
    assert len(detect_calls) == 1


def test_graph_has_single_l0_entrypoint():
  import inspect
  from backend.pipeline import graph as graph_mod

  src = inspect.getsource(graph_mod.build_pipeline)
  assert src.count('"analyze_parallel"') >= 2
  assert "orchestrator" in src
  assert "detect_intent" not in src
