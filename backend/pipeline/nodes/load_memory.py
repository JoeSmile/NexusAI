"""加载记忆节点 — 经 UnifiedMemoryService.read（Task 34.03）。"""

from __future__ import annotations

from backend.core.memory_service import get_unified_memory_service
from backend.observability.decorators import observe
from backend.pipeline.state import PipelineState


@observe(name="pipeline.load_memory")
async def load_memory(state: PipelineState) -> PipelineState:
    """加载用户记忆（hot/warm/cold）。"""
    tenant_id = state["tenant_id"]
    user_id = state["user_id"]
    session_id = state.get("session_id")

    svc = get_unified_memory_service(tenant_id=tenant_id)
    bundle = await svc.read(
        user_id=user_id,
        session_id=None,  # 与旧行为一致：跨 session 最近对话
        hot_limit=5,
        include_warm=True,
        include_cold=True,
    )
    # 兼容旧 state 键；cold 新增
    state["hot_memory"] = bundle.hot
    state["warm_memory"] = bundle.warm
    state["cold_memory"] = bundle.cold
    # session_id 保留供下游；read 未按 session 过滤 hot（历史行为）
    _ = session_id
    return state
