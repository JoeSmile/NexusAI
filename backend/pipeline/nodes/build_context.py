"""上下文组装节点 — 经 UnifiedMemoryService 预算组装 + 漂移检测（Task 34.05/34.06）。"""

from __future__ import annotations

from backend.core.guardrails.output_guard import check_role_drift
from backend.core.memory_service import (
    MEMORY_ISOLATION_HEADER,
    MemoryBundle,
    get_unified_memory_service,
)
from backend.observability.decorators import enrich_span, observe
from backend.pipeline.state import PipelineState


@observe(name="pipeline.build_context")
async def build_context(state: PipelineState) -> PipelineState:
    """组装最终上下文（记忆段带隔离标记 + token 预算；漂移则剥离记忆正文）。"""
    mem = get_unified_memory_service(tenant_id=state["tenant_id"])
    bundle = MemoryBundle(
        hot=list(state.get("hot_memory") or []),
        warm=dict(state.get("warm_memory") or {}),
        cold=list(state.get("cold_memory") or []),
    )
    memory_block = mem.assemble_prompt_block(bundle)
    drift_blocked = False
    if memory_block:
        drift = await check_role_drift(memory_block)
        if drift.action == "blocked":
            # 保留隔离头，丢弃可能污染人设的记忆正文
            memory_block = MEMORY_ISOLATION_HEADER
            drift_blocked = True
    parts = [memory_block] if memory_block else []
    parts.append(f"user: {state['message']}")
    state["raw_input"] = "\n\n".join(parts)
    enrich_span(
        input_data={"message": state.get("message")},
        output_data={"raw_input_len": len(state["raw_input"] or "")},
        metadata={
            "intent": state.get("intent"),
            "cold_count": len(bundle.cold),
            "hot_count": len(bundle.hot),
            "memory_drift_blocked": drift_blocked,
        },
    )
    return state
