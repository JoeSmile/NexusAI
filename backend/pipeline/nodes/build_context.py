"""上下文组装节点"""

from __future__ import annotations

from backend.pipeline.state import PipelineState


async def build_context(state: PipelineState) -> PipelineState:
    """组装最终上下文"""
    context_parts = []

    if state["warm_memory"]:
        profile_str = "用户信息: " + ", ".join(
            f"{k}={v}" for k, v in state["warm_memory"].items()
        )
        context_parts.append(profile_str)

    for msg in state["hot_memory"][-3:]:
        context_parts.append(f"{msg['role']}: {msg['content']}")

    context_parts.append(f"user: {state['message']}")
    state["raw_input"] = "\n".join(context_parts)
    return state
