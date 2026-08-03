"""加载记忆节点 — 经 UnifiedMemoryService.read（Task 34.03/34.05）。"""

from __future__ import annotations

from backend.core.memory_service import get_unified_memory_service
from backend.observability.decorators import observe
from backend.pipeline.state import PipelineState


@observe(name="pipeline.load_memory")
async def load_memory(state: PipelineState) -> PipelineState:
    """加载用户记忆（hot/warm/cold）。"""
    svc = get_unified_memory_service(tenant_id=state["tenant_id"])
    bundle = await svc.read(
        user_id=state["user_id"],
        session_id=None,
        hot_limit=5,
        include_warm=True,
        include_cold=True,
    )
    state["hot_memory"] = bundle.hot
    state["warm_memory"] = bundle.warm
    state["cold_memory"] = bundle.cold
    return state
