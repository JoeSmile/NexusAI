"""输入护栏节点 — 注入检测 + PII 脱敏"""

from __future__ import annotations

from backend.core.guardrails.input_guard import check_input
from backend.core.metrics import guardrails_blocked
from backend.observability.decorators import observe
from backend.pipeline.state import PipelineState


@observe(name="pipeline.guardrails_input")
async def guardrails_input(state: PipelineState) -> PipelineState:
    """输入安全检查"""
    result = await check_input(state["message"])

    if result.action == "blocked":
        state["prompt_injection_detected"] = True
        state["guardrails_passed"] = False
        state["response"] = "输入内容不符合安全规范，已被拦截。"
        state["finish_reason"] = "blocked"
        state["error_code"] = "GUARD_001"
        guardrails_blocked.labels(
            tenant=state["tenant_id"], guard="injection"
        ).inc()
        return state

    if result.action == "redacted":
        state["pii_redacted"] = True
        state["message"] = result.redacted_text
        guardrails_blocked.labels(
            tenant=state["tenant_id"], guard="pii"
        ).inc()

    state["guardrails_passed"] = True
    return state


def should_block_to_end(state: PipelineState) -> str:
    """条件边: 护栏拦截 → END"""
    if state.get("finish_reason") == "blocked" or not state.get(
        "guardrails_passed", True
    ):
        return "end"
    return "continue"
