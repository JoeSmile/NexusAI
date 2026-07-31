"""认证节点 — 注入 user_context"""

from __future__ import annotations

from backend.pipeline.state import PipelineState


async def auth_check(state: PipelineState) -> PipelineState:
    """
    注入 user_context。

    实际认证在 FastAPI Depends(verify_api_key) 中完成，
    节点直接从 state 获取已认证的 user_context。
    """
    if not state.get("user_context"):
        state["user_context"] = {
            "tenant_id": state["tenant_id"],
            "user_id": state["user_id"],
            "permissions": [],
            "role": "",
        }
    return state
