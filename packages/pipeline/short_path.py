"""Shared skill short-path predicate and executor (S3)."""

from __future__ import annotations

from packages.observability.decorators import enrich_span
from packages.observability.sampling import set_tracing_enabled, should_sample
from packages.pipeline.intent_path import (
    SHORT_PATH_CONFIDENCE,
    resolve_short_path_skill,
    skill_to_state,
)
from packages.pipeline.nodes.guardrails_output import apply_generation_exit_to_state
from packages.pipeline.state import PipelineState
from packages.skills.registry import registry


def should_take_skill_short_path(
    state: PipelineState,
    *,
    attachments_present: bool | None = None,
) -> bool:
    """Four-tuple gate: confidence, skill, no attachments, funnel not blocking."""
    confidence = float(state.get("intent_confidence") or 0.0)
    if confidence < SHORT_PATH_CONFIDENCE:
        return False
    if resolve_short_path_skill(state) is None:
        return False
    if state.get("funnel_block_short_path"):
        return False
    if attachments_present is None:
        attachments_present = bool(state.get("file_blocks"))
    return not attachments_present


async def execute_skill_short_path(state: PipelineState) -> PipelineState:
    """Run the resolved skill. SKILL_001 → finish_reason=error, do not swallow."""
    intent = state.get("intent", "default") or "default"
    skill = resolve_short_path_skill(state)
    state["short_path_skill"] = skill_to_state(skill)
    if skill is None:
        state["finish_reason"] = "error"
        state["error_code"] = "SKILL_001"
        state["response"] = "Skill 执行错误: missing_skill"
        return state
    try:
        result = await registry.execute_skill(
            skill_id=skill.id,
            entities=state.get("entities") or {},
            tenant_id=state["tenant_id"],
            user_context=state.get("user_context") or {},
        )
        state["response"] = result.output
        state["finish_reason"] = (
            "skill_executed" if result.success else (result.error or "error")
        )
        state["total_cost"] = 0.0
        state["pipeline_latency_ms"] = result.latency_ms
        if result.error == "PENDING_APPROVAL":
            state["approval_request_id"] = result.approval_request_id
        if result.error:
            state["error_code"] = result.error
        try:
            state = await apply_generation_exit_to_state(state)
        except Exception:
            import logging

            logging.getLogger(__name__).exception("short-path generation exit failed")
        enrich_span(
            metadata={
                "path": "short",
                "intent": intent,
                "skill_id": skill.id,
            },
            output_data=state.get("finish_reason"),
        )
        if not should_sample(state["finish_reason"]):
            set_tracing_enabled(False)
        return state
    except Exception as e:
        state["response"] = f"Skill 执行错误: {e!s}"
        state["finish_reason"] = "error"
        state["error_code"] = "SKILL_001"
        return state
