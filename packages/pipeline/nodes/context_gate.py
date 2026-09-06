"""Attachment probe + short-path vs long-path routing (S3)."""

from __future__ import annotations

from packages.observability.decorators import observe
from packages.pipeline.intent_path import resolve_short_path_skill, skill_to_state
from packages.pipeline.session_attachments import session_has_ready_attachments
from packages.pipeline.short_path import should_take_skill_short_path
from packages.pipeline.state import PipelineState
from packages.thread_pool import run_in_io_pool


@observe(name="pipeline.context_gate")
async def context_gate(state: PipelineState) -> PipelineState:
    """Probe ready attachments; write session_attachment_present for inject."""
    skill = resolve_short_path_skill(state)
    state["short_path_skill"] = skill_to_state(skill)
    if state.get("triggered_run") or state.get("finish_reason") == "workflow_triggered":
        return state
    try:
        present = await run_in_io_pool(
            session_has_ready_attachments,
            str(state.get("tenant_id") or ""),
            str(state.get("user_id") or ""),
            str(state.get("session_id") or ""),
        )
    except Exception:
        # Probe failure: fail closed to the long path so attachments are not skipped.
        present = True
    state["session_attachment_present"] = bool(present)
    return state


def route_after_context_gate(state: PipelineState) -> str:
    if state.get("triggered_run") or state.get("finish_reason") == "workflow_triggered":
        return "write_memory"
    present = bool(state.get("session_attachment_present"))
    if should_take_skill_short_path(state, attachments_present=present):
        return "run_skill"
    return "build_context"
