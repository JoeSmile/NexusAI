"""L2 intent drift detection — event-driven replan signals (Task 64)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from packages.plan.models import PlanStep

_USER_CORRECTION = re.compile(
    r"(算了|换一个|不要了|改成|其实我想|不对|重新来|别抓|停止)",
    re.IGNORECASE,
)
_TOOL_REVEAL = re.compile(
    r"(并不是|不符合预期|您可能要的是|建议改为|其实是竞品|意图.*变化)",
    re.IGNORECASE,
)
_FAILURE_DRIFT = re.compile(
    r"(unsupported|not_found|不支持|无法执行|意图错位|capability.*not|unknown.*cap)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DriftAssessment:
    signal: str  # user_correction | tool_reveal | step_failure
    detail: str
    original_goal: str = ""
    step_id: str = ""
    capability_id: str = ""


def detect_intent_drift(
    *,
    goal: str,
    user_message: str,
    step: PlanStep,
    outcome: dict[str, Any] | None = None,
    error: str | None = None,
) -> DriftAssessment | None:
    """Rule-based drift signals; optional LLM judge deferred to replan prompt."""
    msg = (user_message or "").strip()
    if msg and _USER_CORRECTION.search(msg):
        return DriftAssessment(
            signal="user_correction",
            detail=msg[:500],
            original_goal=goal[:500],
            step_id=step.id,
            capability_id=step.capability_id,
        )

    if error:
        err = error[:500]
        if _FAILURE_DRIFT.search(err):
            return DriftAssessment(
                signal="step_failure",
                detail=err,
                original_goal=goal[:500],
                step_id=step.id,
                capability_id=step.capability_id,
            )

    if outcome and outcome.get("ok"):
        text = str(outcome.get("output") or outcome.get("text") or "")[:2000]
        if text and _TOOL_REVEAL.search(text):
            return DriftAssessment(
                signal="tool_reveal",
                detail=text[:500],
                original_goal=goal[:500],
                step_id=step.id,
                capability_id=step.capability_id,
            )

    return None


def audit_intent_drift(
    *,
    tenant_id: str,
    user_id: str,
    trace_id: str,
    assessment: DriftAssessment,
) -> None:
    from packages.audit import write_audit_sync

    explain = json.dumps(
        {
            "signal": assessment.signal,
            "detail": assessment.detail,
            "original_goal": assessment.original_goal,
            "step_id": assessment.step_id,
            "capability_id": assessment.capability_id,
        },
        ensure_ascii=False,
    )
    write_audit_sync(
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "action": "plan.intent_drift",
            "trace_id": trace_id,
            "input_text": assessment.original_goal[:500],
            "output_text": explain[:4000],
            "decision_explain": explain[:4000],
            "created_at": datetime.utcnow(),
        }
    )
