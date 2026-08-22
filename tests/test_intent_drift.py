"""Task 64 slice 3 — L2 intent drift detection."""

from __future__ import annotations

from backend.core.plan.intent_drift import detect_intent_drift
from backend.core.plan.models import PlanStep


def _step() -> PlanStep:
    return PlanStep(id="s1", capability_id="hotspot.dig", params={})


def test_user_correction_signal():
    drift = detect_intent_drift(
        goal="抓热点",
        user_message="算了换一个方向，做竞品分析",
        step=_step(),
    )
    assert drift is not None
    assert drift.signal == "user_correction"


def test_tool_reveal_signal():
    drift = detect_intent_drift(
        goal="抓热点",
        user_message="抓热点",
        step=_step(),
        outcome={"ok": True, "output": "您可能要的是竞品分析而不是热搜"},
    )
    assert drift is not None
    assert drift.signal == "tool_reveal"


def test_step_failure_signal():
    drift = detect_intent_drift(
        goal="写脚本",
        user_message="写脚本",
        step=_step(),
        error="unsupported_content_ops capability not found",
    )
    assert drift is not None
    assert drift.signal == "step_failure"


def test_no_drift_on_clean_run():
    assert (
        detect_intent_drift(
            goal="抓热点",
            user_message="抓热点",
            step=_step(),
            outcome={"ok": True, "output": "找到 5 条热点"},
        )
        is None
    )
