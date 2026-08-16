"""输出护栏节点 — 长度截断 + 敏感内容 + G7 学员脱敏。"""

from __future__ import annotations

import logging

from backend.core.guardrails.output_guard import check_output
from backend.observability.decorators import observe
from backend.pipeline.state import PipelineState

logger = logging.getLogger(__name__)


def apply_student_output_redaction(state: PipelineState) -> None:
    """G7 拍板 1B：生成出口强制脱敏（口播/长路径/短路径共用）。"""
    text = state.get("response")
    if not text or not isinstance(text, str):
        return
    tenant_id = str(state.get("tenant_id") or "")
    if not tenant_id:
        return
    try:
        from backend.core.memory_service import redact_student_names_in_text

        warm = dict(state.get("warm_memory") or {})
        redacted = redact_student_names_in_text(
            text, tenant_id=tenant_id, warm=warm
        )
        if redacted != text:
            state["response"] = redacted
            state["student_pii_redacted"] = True
    except Exception:
        logger.debug("student output redaction skipped", exc_info=True)


@observe(name="pipeline.guardrails_output")
async def guardrails_output(state: PipelineState) -> PipelineState:
    """输出安全检查"""
    result = await check_output(state.get("response") or "")

    if result.action == "blocked":
        state["response"] = result.redacted_text
        state["finish_reason"] = "blocked"
        state["error_code"] = "GUARD_003"
        apply_student_output_redaction(state)
        return state

    if result.action == "truncated":
        state["response"] = result.redacted_text

    apply_student_output_redaction(state)
    return state
