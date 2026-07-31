"""输出护栏节点 — 长度截断 + 敏感内容"""

from __future__ import annotations

from backend.core.guardrails.output_guard import check_output
from backend.observability.decorators import observe
from backend.pipeline.state import PipelineState


@observe(name="pipeline.guardrails_output")
async def guardrails_output(state: PipelineState) -> PipelineState:
    """输出安全检查"""
    result = await check_output(state.get("response") or "")

    if result.action == "blocked":
        state["response"] = result.redacted_text
        state["finish_reason"] = "blocked"
        state["error_code"] = "GUARD_003"
        return state

    if result.action == "truncated":
        state["response"] = result.redacted_text

    return state
