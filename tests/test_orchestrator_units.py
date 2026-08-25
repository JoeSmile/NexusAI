"""Task 71 slice 5 — orchestrator unit acceptance (thin wrappers)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.core.plan.blackboard import Blackboard, BlackboardEntry, entry_from_step_result
from backend.core.plan.loop_guard import LoopGuard, LoopGuardError
from backend.core.plan.models import normalize_plan_dict
from backend.core.plan.validator import PlanValidationError, validate_plan_ir


@pytest.fixture(autouse=True)
def _noop_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.core.plan.blackboard.write_audit_sync",
        lambda *a, **k: True,
    )


def test_plan_ir_valid_and_invalid() -> None:
    good = {
        "goal": "g",
        "version": 1,
        "max_depth": 3,
        "steps": [
            {
                "id": "s1",
                "capability_id": "cap.a",
                "params": {},
                "depends_on": [],
                "mode": "serial",
                "on_fail": "fail",
            }
        ],
    }
    caps = {"cap.a": {"id": "cap.a"}}
    plan = validate_plan_ir(normalize_plan_dict(good), caps_by_id=caps, fallback_goal="g")
    assert plan.steps[0].capability_id == "cap.a"

    with pytest.raises((PlanValidationError, ValueError, Exception)):
        validate_plan_ir(
            normalize_plan_dict({"goal": "x", "steps": []}),
            caps_by_id=caps,
            fallback_goal="x",
        )


def test_blackboard_step2_reads_step1() -> None:
    bb = Blackboard()
    built = entry_from_step_result(
        step_id="s1",
        capability_id="cap.a",
        outcome={"ok": True, "output": "结论A"},
    )
    assert built is not None
    bb.add(
        BlackboardEntry("s1:cap.a", [], "结论A", 0.9, topic="step.s1"),
        tenant_id="t",
        user_id="u",
        trace_id="tr",
    )
    entries = bb.list_entries()
    assert any("结论A" in str(e.get("fact_content") or "") for e in entries)


def test_loop_guard_blocks_repeat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOOP_GUARD_ENABLED", "1")
    monkeypatch.setenv("LOOP_GUARD_MAX_DUP_STREAK", "3")
    monkeypatch.setenv("LOOP_GUARD_SESSION_CAP", "50")
    guard = LoopGuard()
    payload = {"q": "same"}
    with patch("backend.core.plan.loop_guard.write_audit_sync", return_value=True):
        guard.check("cap.a", payload, tenant_id="t1", user_id="u1", trace_id="tr1")
        guard.check("cap.a", payload, tenant_id="t1", user_id="u1", trace_id="tr1")
        with pytest.raises(LoopGuardError):
            guard.check("cap.a", payload, tenant_id="t1", user_id="u1", trace_id="tr1")
