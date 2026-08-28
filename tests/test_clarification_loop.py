"""Task 65 slice 6 — clarification loop triggers + session resume."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest

from packages.plan.clarification import (
    CLARIFY_CONFIDENCE_MAX,
    ClarificationPayload,
    evaluate_clarification_triggers,
    get_pending,
    store_pending,
    try_resolve_pending,
    warm_pending_key,
)
from packages.pipeline.nodes.clarification_gate import (
    clarification_gate,
    route_after_clarification,
)
from packages.pipeline.state import make_initial_state


def _seed_warm(state: dict, payload: ClarificationPayload) -> None:
    key = warm_pending_key(str(state.get("session_id") or "default"))
    state["warm_memory"] = {key: json.dumps(payload.to_dict(), ensure_ascii=False)}


@pytest.fixture(autouse=True)
def _mock_warm_write(monkeypatch):
    writes: list[dict] = []

    async def _write(self, tier, *, user_id, **payload):
        writes.append({"tier": tier, "user_id": user_id, **payload})
        return {"tier": tier, "key": payload.get("key")}

    monkeypatch.setattr(
        "backend.core.memory_service.UnifiedMemoryService.write",
        _write,
    )
    monkeypatch.setattr(
        "backend.database.vector_ops.delete_user_memory",
        lambda *a, **k: True,
    )
    yield writes


def test_low_confidence_triggers_clarification():
    state = make_initial_state("t1", "u1", "s1", "帮我看看")
    state["intent_confidence"] = CLARIFY_CONFIDENCE_MAX - 0.1
    payload = evaluate_clarification_triggers(state)
    assert payload is not None
    assert payload.source == "low_confidence"


def test_rewrite_flag_triggers_clarification():
    state = make_initial_state("t1", "u1", "s1", "查一下")
    state["intent_confidence"] = 0.9
    state["query_rewrite"] = {"clarification_needed": True}
    payload = evaluate_clarification_triggers(state)
    assert payload is not None
    assert payload.source == "rewrite_flag"


def test_missing_entities_triggers_clarification():
    state = make_initial_state("t1", "u1", "s1", "它的收益怎么样？")
    state["intent_confidence"] = 0.9
    state["intent"] = "knowledge_query"
    state["entities"] = {}
    payload = evaluate_clarification_triggers(state)
    assert payload is not None
    assert payload.source == "missing_entities"


@pytest.mark.asyncio
async def test_resolve_pending_merges_answer(monkeypatch):
    audits: list[dict] = []
    monkeypatch.setattr(
        "packages.plan.clarification.write_audit_sync",
        lambda rec: audits.append(dict(rec)) or True,
    )
    state = make_initial_state("t1", "u1", "s1", "汇丰银行")
    _seed_warm(
        state,
        ClarificationPayload(
            source="missing_entities",
            question="哪个对象？",
            trace_id="tr_test",
            original_query="它的收益怎么样",
        ),
    )
    state["message"] = "汇丰银行"
    assert await try_resolve_pending(state) is True
    assert state["clarification_resolved"] is True
    assert "汇丰银行" in state["message"]
    assert state["query_rewrite"]["clarification_needed"] is False
    assert audits and audits[-1]["action"] == "chat.clarify"


@pytest.mark.asyncio
async def test_clarification_gate_holds_pipeline(monkeypatch):
    audits: list[dict] = []
    monkeypatch.setattr(
        "packages.plan.clarification.write_audit_sync",
        lambda rec: audits.append(dict(rec)) or True,
    )
    state = make_initial_state("t1", "u1", "s1", "帮我看看")
    state["intent_confidence"] = 0.1
    out = await clarification_gate(state)
    assert out["pending_clarification"] is True
    assert out["finish_reason"] == "clarification_pending"
    assert out["task_plan"] is None
    assert out["response"]
    assert route_after_clarification(out) == "hold"
    assert await get_pending(state) is not None
    key = warm_pending_key("s1")
    assert key in (out.get("warm_memory") or {})
    assert any(a["action"] == "chat.clarify" for a in audits)


@pytest.mark.asyncio
async def test_clarification_gate_resume_continues(monkeypatch):
    monkeypatch.setattr(
        "packages.plan.clarification.write_audit_sync",
        lambda rec: True,
    )
    state = make_initial_state("t1", "u1", "s1", "查汇丰理财产品")
    _seed_warm(
        state,
        ClarificationPayload(
            source="rewrite_flag",
            question="请说明目标",
            trace_id="tr_resume",
            original_query="查一下",
        ),
    )
    out = await clarification_gate(state)
    assert out.get("pending_clarification") is False
    assert out.get("clarification_resolved") is True
    assert route_after_clarification(out) == "continue"


@pytest.mark.asyncio
async def test_pending_timeout_audit(monkeypatch):
    audits: list[dict] = []
    monkeypatch.setattr(
        "packages.plan.clarification.write_audit_sync",
        lambda rec: audits.append(dict(rec)) or True,
    )
    state = make_initial_state("t1", "u1", "s1", "hi")
    state["trace_id"] = "tr_timeout"
    _seed_warm(
        state,
        ClarificationPayload(
            source="low_confidence",
            question="?",
            trace_id="tr_timeout",
            original_query="hi",
            created_at=time.time() - 120,
        ),
    )
    assert await get_pending(state, audit_on_timeout=True) is None
    assert any(
        a["action"] == "chat.clarify" and "timeout" in (a.get("output_text") or "")
        for a in audits
    )


def test_high_risk_incomplete_tool_trigger(monkeypatch):
    class FakeSpec:
        spec = {"risk_level": "high"}

    reg = MagicMock()
    reg.get.return_value = FakeSpec()
    monkeypatch.setattr(
        "packages.capability.registry.get_capability_registry",
        lambda: reg,
    )
    state = make_initial_state("t1", "u1", "s1", "执行操作")
    state["intent_confidence"] = 0.95
    state["task_plan"] = {
        "steps": [{"capability_id": "danger.tool", "params": {}}],
    }
    payload = evaluate_clarification_triggers(state)
    assert payload is not None
    assert payload.source == "high_risk_tool"


def test_required_slots_triggers_even_when_clarification_resolved():
    state = make_initial_state("t1", "u1", "s1", "介绍一下")
    state["clarification_resolved"] = True
    state["agent_type_id"] = "pre_sales_agent"
    state["slot_values"] = {}
    payload = evaluate_clarification_triggers(state)
    assert payload is not None
    assert payload.source == "required_slots"


@pytest.mark.asyncio
async def test_store_pending_writes_warm_key(monkeypatch, _mock_warm_write):
    state = make_initial_state("t1", "u1", "s1", "q")
    payload = ClarificationPayload(
        source="low_confidence",
        question="?",
        trace_id="tr_warm",
        original_query="q",
    )
    await store_pending(state, payload)
    key = warm_pending_key("s1")
    assert key in state["warm_memory"]
    assert _mock_warm_write
    assert _mock_warm_write[-1]["key"] == key
    assert _mock_warm_write[-1]["source"] == "clarification"


@pytest.mark.asyncio
async def test_fetch_pending_from_db_when_warm_empty(monkeypatch):
    row = ClarificationPayload(
        source="rewrite_flag",
        question="?",
        trace_id="tr_db",
        original_query="x",
    )
    monkeypatch.setattr(
        "backend.database.vector_ops.list_user_memories_by_prefix",
        lambda *a, **k: [{"value": json.dumps(row.to_dict(), ensure_ascii=False)}],
    )
    state = make_initial_state("t1", "u1", "s1", "answer")
    pending = await get_pending(state)
    assert pending is not None
    assert pending["trace_id"] == "tr_db"
    assert warm_pending_key("s1") in state["warm_memory"]
