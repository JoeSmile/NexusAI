"""Task 61-s3 P2 — incremental blackboard prompt delivery."""

from __future__ import annotations

import pytest

from packages.plan.blackboard import Blackboard


@pytest.fixture(autouse=True)
def _noop_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "packages.plan.blackboard.write_audit_sync",
        lambda *a, **k: True,
    )


def test_project_for_prompt_skips_seen() -> None:
    bb = Blackboard()
    bb.add_topic(topic="step.a", fact_content="A", source_agent_id="a", confidence=0.9)
    bb.add_topic(topic="step.b", fact_content="B", source_agent_id="b", confidence=0.9)
    seen = {
        next(
            e.entry_id
            for e in bb.project_entries(limit=10)
            if e.fact_content == "A"
        )
    }
    batch1 = bb.project_for_prompt(seen_fact_ids=set())
    assert len(batch1) == 2
    batch2 = bb.project_for_prompt(seen_fact_ids=seen)
    assert all(e.entry_id not in seen for e in batch2)


def test_dirty_forces_reentry() -> None:
    bb = Blackboard()
    bb.add_topic(topic="step.x", fact_content="v1", source_agent_id="x", confidence=0.9)
    eid = bb.list_entries()[0]["entry_id"]
    bb.mark_seen({eid}, [eid])
    bb.add_topic(
        topic="step.x",
        fact_content="v2 conflict",
        source_agent_id="x",
        confidence=0.95,
    )
    out = bb.project_for_prompt(seen_fact_ids={eid})
    assert len(out) == 1
    assert out[0].entry_id != eid or out[0].dirty


def test_synthesize_returns_newly_seen_ids() -> None:
    bb = Blackboard()
    bb.add_topic(topic="step.a", fact_content="A", source_agent_id="a", confidence=0.9)
    text, newly_seen = bb.synthesize("goal", seen_fact_ids=set())
    assert "A" in text
    assert len(newly_seen) == 1


def test_mark_seen_clears_dirty() -> None:
    bb = Blackboard()
    bb.add_topic(topic="step.a", fact_content="A", source_agent_id="a", confidence=0.9)
    eid = bb.list_entries()[0]["entry_id"]
    entry = bb._by_id[eid]
    entry.dirty = True
    merged = bb.mark_seen(set(), [eid])
    assert eid in merged
    assert bb._by_id[eid].dirty is False
