"""Task 71 slice 2 — clarification copy must not leak internals."""

from __future__ import annotations

import re

import pytest

from packages.plan.agent_type import get_agent_type
from packages.plan.slot_gate import evaluate_required_slots


@pytest.fixture(autouse=True)
def _noop_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "packages.plan.blackboard.write_audit_sync",
        lambda *a, **k: True,
    )


_INTERNAL_LEAK = re.compile(
    r"(agent_type|required_slots|product_scope|issue_type|pre_sales_agent|"
    r"after_sales_agent|售前顾问|售后专员)",
    re.I,
)


def test_slot_gate_question_has_no_internal_names() -> None:
    at = get_agent_type("pre_sales_agent")
    assert at is not None
    state = {
        "agent_type_id": "pre_sales_agent",
        "slot_values": {},
        "trace_id": "tr-safe",
        "message": "你们产品多少钱",
        "raw_input": "你们产品多少钱",
    }
    payload = evaluate_required_slots(state)
    assert payload is not None
    assert _INTERNAL_LEAK.search(payload.question) is None
    assert "请问您需要补充" in payload.question


def test_slot_gate_options_empty_no_dead_button() -> None:
    state = {
        "agent_type_id": "after_sales_agent",
        "slot_values": {},
        "trace_id": "tr-opt",
        "message": "我要退款",
        "raw_input": "我要退款",
    }
    payload = evaluate_required_slots(state)
    assert payload is not None
    assert payload.options == []
    assert _INTERNAL_LEAK.search(payload.question) is None


def test_clarification_uses_chinese_hints_not_role() -> None:
    state = {
        "agent_type_id": "pre_sales_agent",
        "slot_values": {},
        "trace_id": "tr",
        "message": "报价",
        "raw_input": "报价",
    }
    payload = evaluate_required_slots(state)
    assert payload is not None
    assert "想了解的产品或方案范围" in payload.question
    assert "售前顾问" not in payload.question
    assert "product_scope" not in payload.question
