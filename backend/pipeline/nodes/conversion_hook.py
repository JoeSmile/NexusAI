"""A/B conversion 钩子 — 短/长路径出口记转化。"""

from __future__ import annotations

from backend.core.ab.service import record_event
from backend.observability.decorators import observe
from backend.pipeline.state import PipelineState


@observe(name="pipeline.conversion_hook")
async def conversion_hook(state: PipelineState) -> PipelineState:
    """有实验且有最终响应时记录 conversion；DB 故障不拖垮管线。"""
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
