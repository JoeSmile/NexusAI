"""Task 43.1 — task_plan node + intent_path gate."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from packages.pipeline.intent_path import (
    resolve_short_path_skill,
    short_path_predicate,
    should_task_plan,
    skill_to_state,
)
from backend.core.plan.validator import PlanValidationError
from packages.pipeline.nodes.task_plan import (
    audit_task_plan_on_success,
    plan_for_audit,
    task_plan,
    validate_task_plan,
)
from packages.pipeline.state import make_initial_state
from backend.skills.base import BaseSkill


class _FakeSkill(BaseSkill):
    id = "fake_skill"
    name = "Fake"
    trigger_intents = ["greeting"]

    async def _do_execute(self, entities: dict, tenant_id: str, user_context: dict):
        return "ok"


@pytest.fixture()
def fake_skill(monkeypatch):
    skill = _FakeSkill()

    class Reg:
        def get_skill(self, skill_id: str):
            return skill if skill_id == skill.id else None

        def get_skill_for_intent(self, intent, confidence, threshold=0.85, text=""):
            if confidence < threshold:
                return None
            if intent == "greeting":
                return skill
            return None

    monkeypatch.setattr("packages.pipeline.intent_path.registry", Reg())
    return skill


def test_should_task_plan_matches_short_path_predicate(fake_skill):
    state = make_initial_state("t", "u", "s", "hi")
    state["intent"] = "greeting"
    state["intent_confidence"] = 0.9
    assert short_path_predicate(state) is True
    assert should_task_plan(state) is False
    assert resolve_short_path_skill(state) is fake_skill

    state2 = make_initial_state("t", "u", "s", "hi")
    state2["intent"] = "greeting"
    state2["intent_confidence"] = 0.9
    # high confidence but no skill
    state2["intent"] = "unknown"
    assert short_path_predicate(state2) is False
    assert should_task_plan(state2) is True


@pytest.mark.asyncio
async def test_task_plan_skips_short_path(fake_skill, monkeypatch):
    called = {"n": 0}

    async def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("should not call llm")

    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan.harness.generate", boom
    )
    state = make_initial_state("t", "u", "s", "hello")
    state["intent"] = "greeting"
    state["intent_confidence"] = 0.95
    out = await task_plan(state)
    assert out.get("task_plan") is None
    assert out.get("short_path_skill") == skill_to_state(fake_skill)
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_task_plan_skips_streaming_path(monkeypatch):
    """A(08-16): stream_mode=True 时跳过规划——plan 无消费方,不调 LLM。"""
    called = {"n": 0}

    async def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("should not call llm on streaming path")

    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan.harness.generate", boom
    )
    monkeypatch.setattr(
        "packages.pipeline.intent_path.registry.get_skill_for_intent",
        lambda *a, **k: None,
    )
    state = make_initial_state("t", "u", "s", "stream this")
    state["stream_mode"] = True
    state["intent"] = "complex"
    state["intent_confidence"] = 0.4
    out = await task_plan(state)
    assert out.get("task_plan") is None
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_task_plan_skips_without_bridge_target(monkeypatch):
    """B(08-16): 租户无已发布带 intent_tags 的 workflow 时跳过——plan 无消费方。"""
    called = {"n": 0}

    async def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("should not call llm without bridge target")

    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan.harness.generate", boom
    )
    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan._tenant_has_bridge_targets",
        lambda tid: False,
    )
    monkeypatch.setattr(
        "packages.pipeline.intent_path.registry.get_skill_for_intent",
        lambda *a, **k: None,
    )
    state = make_initial_state("t", "u", "s", "no bridge here")
    state["intent"] = "complex"
    state["intent_confidence"] = 0.4
    out = await task_plan(state)
    assert out.get("task_plan") is None
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_task_plan_produces_plan_on_long_path(monkeypatch):
    plan = {
        "steps": [
            {"capability_id": "cap.a", "params": {}, "decision": None},
        ]
    }

    async def fake_gen(*a, **k):
        return SimpleNamespace(
            success=True,
            output=__import__("json").dumps(plan),
            error=None,
            metadata={},
            latency_ms=1.0,
        )

    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan.harness.generate", fake_gen
    )
    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan._list_visible_capabilities",
        lambda state: [
            {"id": "cap.a", "name": "A", "permission": "chat:write", "param_spec": {}}
        ],
    )
    monkeypatch.setattr(
        "packages.pipeline.intent_path.registry.get_skill_for_intent",
        lambda *a, **k: None,
    )

    state = make_initial_state("t", "u", "s", "plan this")
    state["intent"] = "complex"
    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan._tenant_has_bridge_targets",
        lambda tid: True,
    )
    state["intent_confidence"] = 0.4
    out = await task_plan(state)
    assert out["task_plan"] is not None
    assert out["task_plan"]["steps"][0]["capability_id"] == "cap.a"
    assert out["task_plan"]["steps"][0]["id"] == "s1"
    assert out.get("query_rewrite") is not None


@pytest.mark.asyncio
async def test_task_plan_runs_on_stream_when_forced(monkeypatch):
    plan = {
        "steps": [{"capability_id": "cap.a", "params": {}, "decision": None}],
    }
    called = {"n": 0}

    async def fake_gen(*a, **k):
        called["n"] += 1
        return SimpleNamespace(
            success=True,
            output=__import__("json").dumps(plan),
            error=None,
            metadata={},
            latency_ms=1.0,
        )

    monkeypatch.setenv("FORCE_TASK_PLAN_ON_STREAM", "1")
    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan.harness.generate", fake_gen
    )
    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan._list_visible_capabilities",
        lambda state: [
            {"id": "cap.a", "name": "A", "permission": "chat:write", "param_spec": {}}
        ],
    )
    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan._tenant_has_bridge_targets",
        lambda tid: True,
    )
    monkeypatch.setattr(
        "packages.pipeline.intent_path.registry.get_skill_for_intent",
        lambda *a, **k: None,
    )
    state = make_initial_state("t", "u", "s", "stream plan")
    state["stream_mode"] = True
    state["intent_confidence"] = 0.2
    out = await task_plan(state)
    assert called["n"] >= 1
    assert out["task_plan"] is not None


@pytest.mark.asyncio
async def test_task_plan_degrades_on_bad_json(monkeypatch):
    async def fake_gen(*a, **k):
        return SimpleNamespace(
            success=True,
            output="not-json",
            error=None,
            metadata={},
            latency_ms=1.0,
        )

    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan.harness.generate", fake_gen
    )
    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan._list_visible_capabilities",
        lambda state: [],
    )
    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan._tenant_has_bridge_targets",
        lambda tid: True,
    )
    monkeypatch.setattr(
        "packages.pipeline.intent_path.registry.get_skill_for_intent",
        lambda *a, **k: None,
    )

    state = make_initial_state("t", "u", "s", "x")
    state["intent_confidence"] = 0.2
    out = await task_plan(state)
    assert out["task_plan"] is None


def test_validate_task_plan_rejects_forbidden_keys():
    with pytest.raises(PlanValidationError, match="forbidden"):
        validate_task_plan(
            {
                "steps": [
                    {
                        "capability_id": "c1",
                        "params": {"api_key": "x"},
                    }
                ]
            },
            caps_by_id={"c1": {"param_spec": {}}},
        )


def test_plan_for_audit_strips_params():
    raw = {
        "steps": [
            {"capability_id": "c1", "params": {"q": "secret"}, "decision": "d"},
        ]
    }
    scrubbed = plan_for_audit(raw)
    assert scrubbed["steps"][0]["capability_id"] == "c1"
    assert scrubbed["steps"][0]["params"] == {}
    assert scrubbed["steps"][0]["decision"] == "d"


@pytest.mark.asyncio
async def test_task_plan_blocks_on_output_guard(monkeypatch):
    plan = {
        "steps": [{"capability_id": "cap.a", "params": {}, "decision": None}],
    }

    async def fake_gen(*a, **k):
        return SimpleNamespace(
            success=True,
            output=__import__("json").dumps(plan),
            error=None,
            metadata={},
            latency_ms=1.0,
        )

    async def blocked(text: str):
        return SimpleNamespace(action="blocked", reason="sensitive_content:sk-", redacted_text="")

    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan.harness.generate", fake_gen
    )
    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan._list_visible_capabilities",
        lambda state: [
            {"id": "cap.a", "name": "A", "permission": "chat:write", "param_spec": {}}
        ],
    )
    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan.check_output", blocked
    )
    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan._tenant_has_bridge_targets",
        lambda tid: True,
    )
    monkeypatch.setattr(
        "packages.pipeline.intent_path.registry.get_skill_for_intent",
        lambda *a, **k: None,
    )
    state = make_initial_state("t", "u", "s", "x")
    state["intent_confidence"] = 0.2
    out = await task_plan(state)
    assert out["task_plan"] is None


def test_audit_only_on_llm_success(monkeypatch):
    calls: list[dict] = []

    def fake_audit(rec):
        calls.append(rec)

    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan.write_audit_sync", fake_audit
    )
    state = make_initial_state("t", "u", "s", "hi")
    state["task_plan"] = {
        "steps": [{"capability_id": "c1", "params": {"x": 1}, "decision": None}]
    }
    state["finish_reason"] = "llm_generated"
    audit_task_plan_on_success(state)
    assert len(calls) == 1
    blob = __import__("json").loads(calls[0]["output_text"])
    assert blob["plan"]["steps"][0]["params"] == {}
    # idempotent
    audit_task_plan_on_success(state)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_async_plan_skipped_when_flag_off(monkeypatch):
    from packages.pipeline.nodes.task_plan import run_async_task_plan_for_stream

    monkeypatch.delenv("ASYNC_TASK_PLAN_ON_STREAM", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_ENABLED", raising=False)
    monkeypatch.delenv("FORCE_TASK_PLAN_ON_STREAM", raising=False)

    async def boom(*a, **k):
        raise AssertionError("should not plan when async flag off")

    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan._produce_plan_ir", boom
    )
    state = make_initial_state("t", "u", "s", "complex please")
    state["stream_mode"] = True
    state["intent"] = "complex"
    state["intent_confidence"] = 0.3
    out, status = await run_async_task_plan_for_stream(state)
    assert status == "skipped"
    assert out.get("task_plan") is None


@pytest.mark.asyncio
async def test_async_plan_ok_emits_done(monkeypatch):
    from backend.core.plan.event_bus import get_run_bus
    from packages.pipeline.nodes.task_plan import run_async_task_plan_for_stream

    monkeypatch.setenv("ASYNC_TASK_PLAN_ON_STREAM", "1")
    monkeypatch.delenv("ORCHESTRATOR_ENABLED", raising=False)
    monkeypatch.delenv("FORCE_TASK_PLAN_ON_STREAM", raising=False)

    plan = {
        "goal": "g",
        "version": 1,
        "max_depth": 3,
        "steps": [
            {
                "id": "s1",
                "capability_id": "cap.a",
                "params": {},
                "depends_on": [],
                "mode": "serial",
                "on_fail": "fail",
            }
        ],
    }

    async def fake_produce(state):
        return plan

    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan._produce_plan_ir", fake_produce
    )
    monkeypatch.setattr(
        "packages.pipeline.intent_path.registry.get_skill_for_intent",
        lambda *a, **k: None,
    )

    state = make_initial_state("t", "u", "s", "do multi step")
    state["stream_mode"] = True
    state["intent"] = "complex"
    state["intent_confidence"] = 0.3
    state["trace_id"] = "trace-async-ok"
    bus = get_run_bus("trace-async-ok")
    bus.publish_task_plan_pending(message="do multi step")

    out, status = await run_async_task_plan_for_stream(state, emit_pending=False)
    assert status == "ok"
    assert out["task_plan"]["goal"] == "g"
    assert out.get("stream_async_plan") is True
    types = [e.type for e in bus.events_all()]
    assert "task_plan_pending" in types
    assert "plan" in types
    assert "task_plan_done" in types


@pytest.mark.asyncio
async def test_async_plan_timeout_degrades(monkeypatch):
    import asyncio

    from backend.core.plan.event_bus import get_run_bus
    from packages.pipeline.nodes.task_plan import run_async_task_plan_for_stream

    monkeypatch.setenv("ASYNC_TASK_PLAN_ON_STREAM", "1")
    monkeypatch.delenv("ORCHESTRATOR_ENABLED", raising=False)

    async def slow_produce(state):
        await asyncio.sleep(2.0)
        return {"goal": "late"}

    monkeypatch.setattr(
        "packages.pipeline.nodes.task_plan._produce_plan_ir", slow_produce
    )
    monkeypatch.setattr(
        "packages.pipeline.intent_path.registry.get_skill_for_intent",
        lambda *a, **k: None,
    )

    state = make_initial_state("t", "u", "s", "slow plan")
    state["stream_mode"] = True
    state["intent"] = "complex"
    state["intent_confidence"] = 0.2
    state["trace_id"] = "trace-async-to"
    bus = get_run_bus("trace-async-to")

    out, status = await run_async_task_plan_for_stream(
        state, timeout_s=0.05, emit_pending=True
    )
    assert status == "timeout"
    assert out.get("task_plan") is None
    assert out.get("task_plan_async_status") == "timeout"
    done = [e for e in bus.events_all() if e.type == "task_plan_done"]
    assert done and done[-1].payload.get("status") == "timeout"
