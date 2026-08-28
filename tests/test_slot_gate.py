"""Task 62 — required_slots slot gate + slots.missing blackboard topic."""

from __future__ import annotations

import json

import pytest

from packages.plan.agent_type import TOPIC_SLOTS_MISSING, get_agent_type
from packages.plan.blackboard import Blackboard
from packages.plan.slot_gate import (
    evaluate_required_slots,
    missing_required_slots,
    write_slots_missing_entry,
)


@pytest.fixture(autouse=True)
def _noop_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "packages.plan.blackboard.write_audit_sync",
        lambda *a, **k: True,
    )


def test_missing_required_slots_detected() -> None:
    at = get_agent_type("pre_sales_agent")
    assert at is not None
    missing = missing_required_slots(at, {})
    assert "product_scope" in missing


def test_evaluate_required_slots_triggers_clarification() -> None:
    state = {
        "agent_type_id": "after_sales_agent",
        "slot_values": {},
        "trace_id": "tr1",
        "message": "我要退款",
        "raw_input": "我要退款",
    }
    payload = evaluate_required_slots(state)
    assert payload is not None
    assert payload.source == "required_slots"
    assert payload.options == []
    assert "issue_type" not in payload.question
    assert "请问您需要补充" in payload.question


def test_write_slots_missing_to_blackboard() -> None:
    at = get_agent_type("pre_sales_agent")
    assert at is not None
    bb = Blackboard()
    write_slots_missing_entry(
        bb,
        agent_type=at,
        missing=["product_scope"],
        tenant_id="t1",
        user_id="u1",
        trace_id="tr1",
    )
    entries = bb.list_entries()
    assert len(entries) == 1
    assert entries[0]["topic"] == TOPIC_SLOTS_MISSING
    body = json.loads(entries[0]["fact_content"])
    assert body["agent_type"] == "pre_sales_agent"
    assert body["missing"] == ["product_scope"]
