"""Task 61-s3 P2 — blackboard entry lifecycle + CAS."""

from __future__ import annotations

import pytest

from backend.core.plan.blackboard import Blackboard


@pytest.fixture(autouse=True)
def _noop_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.core.plan.blackboard.write_audit_sync",
        lambda *a, **k: True,
    )


def test_begin_complete_lifecycle() -> None:
    bb = Blackboard()
    eid = bb.begin_pending(
        topic="step.s1",
        fact_content="…",
        source_agent_id="s1:cap",
        confidence=0.5,
    )
    row = bb.get_entry(eid)
    assert row is not None
    assert row["status"] == "pending"
    assert bb.complete_entry(eid, fact_content="done", confidence=0.9)
    assert bb.get_entry(eid)["status"] == "completed"
    assert bb.get_entry(eid)["fact_content"] == "done"


def test_fail_entry_on_error() -> None:
    bb = Blackboard()
    eid = bb.begin_pending(
        topic="step.s2",
        fact_content="…",
        source_agent_id="s2:cap",
        confidence=0.5,
    )
    assert bb.fail_entry(eid, error="timeout")
    row = bb.get_entry(eid)
    assert row is not None
    assert row["status"] == "failed"
    assert row["error"] == "timeout"


def test_cas_rejects_stale_version() -> None:
    bb = Blackboard()
    bb.add_topic(topic="step.s3", fact_content="v1", source_agent_id="a", confidence=0.8)
    entry = bb._by_topic["step.s3"]
    ok = bb.cas_update_topic("step.s3", expected_version=entry.version, entry=entry)
    assert ok is True
    stale = bb.cas_update_topic("step.s3", expected_version=entry.version, entry=entry)
    assert stale is False


def test_fail_stale_pending_on_run_end() -> None:
    bb = Blackboard()
    bb.begin_pending(
        topic="step.s4",
        fact_content="…",
        source_agent_id="s4:cap",
        confidence=0.5,
    )
    n = bb.fail_stale_pending(error="run_ended_incomplete")
    assert n == 1
    assert bb.list_entries()[0]["status"] == "failed"
