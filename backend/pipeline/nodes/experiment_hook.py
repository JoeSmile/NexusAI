"""A/B 实验钩子 — build_context 之后注入变体配置。"""

from __future__ import annotations

from backend.core.ab.service import assign_variant, record_event
from backend.observability.decorators import langfuse_context, observe
from backend.pipeline.state import PipelineState


@observe(name="pipeline.experiment_hook")
async def experiment_hook(state: PipelineState) -> PipelineState:
    """按用户确定性分流，写入 ab_* 字段并记录曝光。"""
    try:
        assignment = assign_variant(state["user_id"])
    except Exception:
        return state
    if not assignment:
        return state

    state["ab_experiment_id"] = assignment["experiment_id"]
    state["ab_variant"] = assignment["variant"]
    state["ab_variant_config"] = assignment.get("variant_config") or {}

    # prompt_prefix 拼进上下文；system_prompt 由 llm_generate 作为 system 消息注入
    cfg = state["ab_variant_config"]
    prefix = cfg.get("prompt_prefix")
    if prefix and isinstance(prefix, str):
        raw = state.get("raw_input") or state.get("message") or ""
        if not raw.startswith(prefix):
            state["raw_input"] = f"{prefix}\n\n{raw}"

    try:
        record_event(
            user_id=state["user_id"],
            experiment_id=assignment["experiment_id"],
            group=assignment["variant"],
            event_type="exposure",
            event_data={"trace_id": state.get("trace_id"), "session_id": state.get("session_id")},
            session_id=state.get("session_id"),
        )
    except Exception:
        pass

    try:
        langfuse_context.update_current_trace(  # type: ignore[attr-defined]
            tags=[
                f"ab:{assignment['experiment_id']}",
                f"variant:{assignment['variant']}",
            ],
            metadata={
                "ab_experiment_id": assignment["experiment_id"],
                "ab_variant": assignment["variant"],
            },
        )
    except Exception:
        pass

    return state
