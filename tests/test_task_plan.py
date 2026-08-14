"""Task 43.1 — task_plan node + intent_path gate."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.pipeline.intent_path import (
    resolve_short_path_skill,
    should_task_plan,
    short_path_predicate,
    skill_to_state,
)
from backend.pipeline.nodes.task_plan import task_plan, validate_task_plan
from backend.pipeline.state import make_initial_state
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

        def get_skill_for_intent(self, intent, confidence, threshold=0.85):
            if confidence < threshold:
                return None
            if intent == "greeting":
                return skill
            return None

    monkeypatch.setattr("backend.pipeline.intent_path.registry", Reg())
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
        "backend.pipeline.nodes.task_plan.harness.generate", boom
    )
    state = make_initial_state("t", "u", "s", "hello")
    state["intent"] = "greeting"
    state["intent_confidence"] = 0.95
    out = await task_plan(state)
    assert out.get("task_plan") is None
    assert out.get("short_path_skill") == skill_to_state(fake_skill)
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
        "backend.pipeline.nodes.task_plan.harness.generate", fake_gen
    )
    monkeypatch.setattr(
        "backend.pipeline.nodes.task_plan._list_visible_capabilities",
        lambda state: [
            {"id": "cap.a", "name": "A", "permission": "chat:write", "param_spec": {}}
        ],
    )
    monkeypatch.setattr(
        "backend.pipeline.nodes.task_plan._audit_plan", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "backend.pipeline.intent_path.registry.get_skill_for_intent",
        lambda *a, **k: None,
    )

    state = make_initial_state("t", "u", "s", "plan this")
    state["intent"] = "complex"
    state["intent_confidence"] = 0.4
    out = await task_plan(state)
    assert out["task_plan"] is not None
    assert out["task_plan"]["steps"][0]["capability_id"] == "cap.a"


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
        "backend.pipeline.nodes.task_plan.harness.generate", fake_gen
    )
    monkeypatch.setattr(
        "backend.pipeline.nodes.task_plan._list_visible_capabilities",
        lambda state: [],
    )
    monkeypatch.setattr(
        "backend.pipeline.intent_path.registry.get_skill_for_intent",
        lambda *a, **k: None,
    )

    state = make_initial_state("t", "u", "s", "x")
    state["intent_confidence"] = 0.2
    out = await task_plan(state)
    assert out["task_plan"] is None


def test_validate_task_plan_rejects_forbidden_keys():
    with pytest.raises(ValueError, match="forbidden"):
        validate_task_plan(
            {
                "steps": [
                    {
                        "capability_id": "c1",
                        "params": {"api_key": "x"},
                    }
                ]
            }
        )
