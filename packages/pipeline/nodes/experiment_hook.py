"""A/B 实验钩子 — clarification 之后写入变体配置与 pending_exposure。"""

from __future__ import annotations

from packages.ab.service import assign_variant
from packages.observability.decorators import langfuse_context, observe
from packages.pipeline.state import PipelineState


@observe(name="pipeline.experiment_hook")
async def experiment_hook(state: PipelineState) -> PipelineState:
    """按用户确定性分流，写入 ab_* 与 pending_exposure（曝光在 conversion_hook 刷新）。"""
    try:
        assignment = assign_variant(state["user_id"])
    except Exception:
        return state
    if not assignment:
        return state

    state["ab_experiment_id"] = assignment["experiment_id"]
    state["ab_variant"] = assignment["variant"]
    state["ab_variant_config"] = assignment.get("variant_config") or {}

    # prompt_prefix → user_prompt_prefix（W6#1）；曝光延后到 conversion_hook
    cfg = state["ab_variant_config"]
    prefix = cfg.get("prompt_prefix")
    if prefix and isinstance(prefix, str):
        state["user_prompt_prefix"] = prefix

    state["pending_exposure"] = assignment

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
