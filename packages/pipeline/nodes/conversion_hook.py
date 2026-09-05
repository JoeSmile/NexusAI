"""A/B conversion 钩子 — 短/长路径出口记转化。"""

from __future__ import annotations

from packages.ab.service import record_event
from packages.observability.decorators import observe
from packages.pipeline.state import PipelineState


@observe(name="pipeline.conversion_hook")
async def conversion_hook(state: PipelineState) -> PipelineState:
    """Flush pending A/B exposure once, then record conversion when a response exists."""
    pending = state.get("pending_exposure")
    if pending:
        try:
            record_event(
                user_id=state["user_id"],
                experiment_id=str(pending.get("experiment_id") or ""),
                group=str(pending.get("variant") or ""),
                event_type="exposure",
                event_data={
                    "trace_id": state.get("trace_id"),
                    "session_id": state.get("session_id"),
                },
                session_id=state.get("session_id"),
            )
        except Exception:
            pass
        state["pending_exposure"] = None

    # CR 4A: Chat 成功终态再写 chat.task_plan（非短路径且有 plan）
    if state.get("finish_reason") == "llm_generated" and state.get("task_plan"):
        try:
            from packages.pipeline.nodes.task_plan import audit_task_plan_on_success

            audit_task_plan_on_success(state)
        except Exception:
            pass

    experiment_id = state.get("ab_experiment_id")
    variant = state.get("ab_variant")
    response = state.get("response")
    if not experiment_id or not variant or not response:
        return state
    try:
        record_event(
            user_id=state["user_id"],
            experiment_id=str(experiment_id),
            group=str(variant),
            event_type="conversion",
            event_data={
                "trace_id": state.get("trace_id"),
                "session_id": state.get("session_id"),
            },
            session_id=state.get("session_id"),
        )
    except Exception:
        pass
    return state
