"""速率限制节点 — 桶令牌检查"""

from __future__ import annotations

from backend.core.errors import ContextGateException
from backend.core.rate_limiter import check_rate_limit
from backend.observability.decorators import observe
from backend.pipeline.state import PipelineState


@observe(name="pipeline.rate_limiter")
async def rate_limiter(state: PipelineState) -> PipelineState:
    """桶令牌检查 — 超出抛 RATE_001"""
    if not check_rate_limit(state["tenant_id"]):
        state["finish_reason"] = "rate_limited"
        state["error_code"] = "RATE_001"
        state["response"] = "请求过于频繁，请稍后再试。"
        raise ContextGateException("RATE_001", "rate_limited")
    return state
