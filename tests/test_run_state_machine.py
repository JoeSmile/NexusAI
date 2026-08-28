"""Wave D1 — run state machine."""

from packages.workflow.run_state import can_transition


def test_legal_transitions():
    assert can_transition("pending", "running")
    assert can_transition("running", "succeeded")
    assert can_transition("running", "failed")
    assert can_transition("running", "suspended")
    assert can_transition("suspended", "running")
    assert not can_transition("pending", "succeeded")
    assert not can_transition("succeeded", "running")
    assert not can_transition("failed", "pending")
