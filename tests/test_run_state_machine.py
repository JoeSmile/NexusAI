"""Wave D1 — run state machine."""

from backend.core.workflow.run_state import can_transition


def test_legal_transitions():
    assert can_transition("pending", "running")
    assert can_transition("running", "succeeded")
    assert can_transition("running", "failed")
    assert not can_transition("pending", "succeeded")
    assert not can_transition("succeeded", "running")
    assert not can_transition("failed", "pending")
    assert not can_transition("running", "suspended")  # Wave E only
