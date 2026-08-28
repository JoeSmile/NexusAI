"""Task 42 S4 — flywheel telemetry (offline)."""

from __future__ import annotations

from packages.memory.flywheel import (
    flywheel_snapshot,
    record_correction_phrase,
    record_item_outcome,
    record_repeat_ask,
    reset_flywheel_for_tests,
)


def setup_function() -> None:
    reset_flywheel_for_tests()


def test_record_accept_reject_counts():
    record_item_outcome(accepted=True, item_type="entity")
    record_item_outcome(accepted=False, reason_code="REJECT_GROUNDING", item_type="entity")
    snap = flywheel_snapshot()
    assert snap["counts"]["accept"] == 1
    assert snap["counts"]["reject"] == 1
    assert snap["counts"]["reject:REJECT_GROUNDING"] == 1


def test_correction_phrase_collects_golden_only():
    assert record_correction_phrase("不是张三是李四") is not None
    snap = flywheel_snapshot()
    assert snap["counts"]["correction"] == 1
    assert snap["golden_candidates"][0]["right"].startswith("李四")
    assert record_correction_phrase("今天开会") is None


def test_repeat_ask_counter():
    record_repeat_ask()
    assert flywheel_snapshot()["counts"]["repeat_ask"] == 1
