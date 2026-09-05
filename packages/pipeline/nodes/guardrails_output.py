"""输出护栏节点 — 共用生成出口（G7 + 教培红线 + 漂移 profile）。"""

from __future__ import annotations

import logging

from packages.guardrails.generation_exit import sanitize_generation_exit
from packages.observability.decorators import observe
from packages.pipeline.state import PipelineState

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
        from packages.memory.memory_service import redact_student_names_in_text

        warm = dict(state.get("warm_memory") or {})
        redacted = redact_student_names_in_text(
            text, tenant_id=tenant_id, warm=warm
        )
        if redacted != text:
            state["response"] = redacted
            state["student_pii_redacted"] = True
    except Exception:
        logger.debug("student output redaction skipped", exc_info=True)


async def apply_generation_exit_to_state(state: PipelineState) -> PipelineState:
    """长/短路径共用：写回 response；BLOCK 时打 finish_reason。"""
    result = await sanitize_generation_exit(
        state.get("response") or "",
        tenant_id=str(state.get("tenant_id") or ""),
        warm=dict(state.get("warm_memory") or {}) or None,
    )
    state["response"] = result.redacted_text
    if result.action == "blocked":
        state["finish_reason"] = "blocked"
        state["error_code"] = "GUARD_003"
        return state
    if "g7_student_pii" in (result.reason or ""):
        state["student_pii_redacted"] = True
    return state


@observe(name="pipeline.guardrails_output")
async def guardrails_output(state: PipelineState) -> PipelineState:
    """输出安全检查"""
    return await apply_generation_exit_to_state(state)
