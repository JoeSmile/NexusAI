"""Task 61-s3 P2 — high-risk Hot pinning and capacity exemption."""

from __future__ import annotations

import pytest

from backend.core.plan.blackboard import Blackboard, is_high_risk


@pytest.fixture(autouse=True)
def _noop_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.core.plan.blackboard.write_audit_sync",
        lambda *a, **k: True,
    )


def test_is_high_risk_by_topic_prefix() -> None:
    bb = Blackboard()
    bb.add_topic(topic="risk.alert", fact_content="x", source_agent_id="r", confidence=0.5)
    entry = bb._by_topic["risk.alert"]
    assert is_high_risk(entry)


def test_is_high_risk_by_risk_level() -> None:
    bb = Blackboard()
    bb.add_topic(
        topic="step.critical",
        fact_content="x",
        source_agent_id="a",
        confidence=0.5,
        risk_level="high",
    )
    entry = bb._by_topic["step.critical"]
    assert is_high_risk(entry)


def test_high_risk_survives_capacity_eviction() -> None:
    bb = Blackboard(capacity=2)
    bb.add_topic(topic="risk.alert", fact_content="风控命中", source_agent_id="r", confidence=0.4)
    bb.add_topic(topic="step.low", fact_content="low", source_agent_id="a", confidence=0.3)
    bb.add_topic(topic="step.mid", fact_content="mid", source_agent_id="b", confidence=0.6)
    topics = {e["topic"] for e in bb.list_entries()}
    assert "risk.alert" in topics
    assert "step.low" not in topics


def test_high_risk_always_in_prompt_projection() -> None:
    bb = Blackboard()
    for i in range(15):
        bb.add_topic(
            topic=f"step.s{i}",
            fact_content=f"f{i}",
            source_agent_id="a",
            confidence=0.9,
        )
    bb.add_topic(
        topic="risk.block",
        fact_content="禁止交易",
        source_agent_id="r",
        confidence=0.2,
    )
    out = bb.project_for_prompt(seen_fact_ids=set())
    assert any(e.topic == "risk.block" for e in out)


def test_high_risk_pinned_even_when_seen() -> None:
    bb = Blackboard()
    bb.add_topic(
        topic="risk.block",
        fact_content="禁止交易",
        source_agent_id="r",
        confidence=0.9,
    )
    eid = bb.list_entries()[0]["entry_id"]
    bb.mark_seen({eid}, [eid])
    out = bb.project_for_prompt(seen_fact_ids={eid})
    assert any(e.topic == "risk.block" for e in out)
