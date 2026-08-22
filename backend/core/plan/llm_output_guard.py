"""LLM output pre-validation — plan tool names + fake tool-call detection (Task 62 slice 3)."""

from __future__ import annotations

import re
from typing import Any

from backend.core.plan.validator import PlanValidationError

_FAKE_TOOL_CALL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<tool_call[\s>]", re.IGNORECASE),
    re.compile(r"</tool_call>", re.IGNORECASE),
    re.compile(r'"tool_calls"\s*:\s*\[', re.IGNORECASE),
    re.compile(r"function_call\s*[:=]", re.IGNORECASE),
    re.compile(r"<function=[^>]+>", re.IGNORECASE),
)


class LlmOutputValidationError(ValueError):
    """LLM plan / tool output failed pre-validation."""


def detect_fake_tool_call_text(text: str) -> bool:
    """Return True when text looks like a forged tool-call block."""
    if not text or not text.strip():
        return False
    return any(p.search(text) for p in _FAKE_TOOL_CALL_PATTERNS)


def scan_plan_for_fake_tool_calls(plan: dict[str, Any]) -> None:
    """Reject plan JSON whose string fields embed fake tool-call markers."""
    for step in plan.get("steps") or []:
        if not isinstance(step, dict):
            continue
        for key, val in step.items():
            if isinstance(val, str) and detect_fake_tool_call_text(val):
                raise LlmOutputValidationError(
                    f"fake tool-call marker in step.{key}"
                )
        params = step.get("params")
        if isinstance(params, dict):
            for pkey, pval in params.items():
                if isinstance(pval, str) and detect_fake_tool_call_text(pval):
                    raise LlmOutputValidationError(
                        f"fake tool-call marker in params.{pkey}"
                    )


def prevalidate_llm_plan(
    plan: dict[str, Any],
    *,
    caps_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Scan for fake markers then ensure every capability_id is whitelisted."""
    if not isinstance(plan, dict):
        raise LlmOutputValidationError("plan root must be object")
    scan_plan_for_fake_tool_calls(plan)
    allowed = set(caps_by_id.keys())
    steps = plan.get("steps") or []
    if not isinstance(steps, list):
        raise LlmOutputValidationError("steps must be a list")
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise LlmOutputValidationError(f"step[{i}] must be object")
        cap_id = step.get("capability_id")
        if not isinstance(cap_id, str) or not cap_id.strip():
            raise LlmOutputValidationError(f"step[{i}] missing capability_id")
        if cap_id not in allowed:
            raise PlanValidationError(f"capability not in whitelist: {cap_id}")
    return plan
