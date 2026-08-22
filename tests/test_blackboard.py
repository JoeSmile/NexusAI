"""Blackboard module (Task 61 slice 3)."""

from __future__ import annotations

import pytest

from backend.core.plan.blackboard import Blackboard, BlackboardEntry, entry_from_step_result


def test_blackboard_rejects_oversized_fact() -> None:
    bb = Blackboard()
    with pytest.raises(ValueError, match="too_long"):
        bb.add(
            BlackboardEntry(
                source_agent_id="s1:cap",
                document_ids_ref=[],
                fact_content="x" * 600,
                confidence=0.9,
            )
        )


def test_blackboard_capacity_evicts_low_confidence() -> None:
    bb = Blackboard(capacity=2, ttl_s=3600)
    bb.add(
        BlackboardEntry("a", [], "low", 0.3),
        tenant_id="t",
        user_id="u",
        trace_id="tr",
    )
    bb.add(
        BlackboardEntry("b", [], "mid", 0.6),
        tenant_id="t",
        user_id="u",
        trace_id="tr",
    )
    bb.add(
        BlackboardEntry("c", [], "high", 0.95),
        tenant_id="t",
        user_id="u",
        trace_id="tr",
    )
    entries = bb.list_entries()
    assert len(entries) == 2
    facts = {e["fact_content"] for e in entries}
    assert "low" not in facts
    assert "high" in facts


def test_entry_from_step_result_rejects_long_output() -> None:
    assert (
        entry_from_step_result(
            step_id="s1",
            capability_id="cap",
            outcome={"output": "x" * 700},
        )
        is None
    )


def test_blackboard_synthesize_includes_refs() -> None:
    bb = Blackboard()
    bb.add(
        BlackboardEntry("s1:cap", ["doc-1"], "结论A", 0.9),
        tenant_id="t",
        user_id="u",
        trace_id="tr",
    )
    text = bb.synthesize("目标X")
    assert "结论A" in text
    assert "doc-1" in text
