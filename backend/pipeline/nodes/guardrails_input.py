"""输入护栏节点 — 占位，具体逻辑在 Batch 5a 补充"""

from __future__ import annotations

from backend.pipeline.state import PipelineState


async def guardrails_input(state: PipelineState) -> PipelineState:
    """输入安全检查 — 占位节点"""
    # TODO(Batch 5a): 接入 Task 09 的完整护栏逻辑
    state["guardrails_passed"] = True
    return state
