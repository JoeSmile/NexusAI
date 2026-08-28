"""速率限制节点 — Redis 分钟桶 + Token TPM/TPD 预检"""

from __future__ import annotations

from backend.core.errors import NexusAIException
from backend.core.rate_limiter import check_rate_limit
from backend.core.token_quota import check_token_quota, estimate_request_tokens
from backend.observability.decorators import observe
from packages.pipeline.state import PipelineState


@observe(name="pipeline.rate_limiter")
async def rate_limiter(state: PipelineState) -> PipelineState:
    """租户 QPS（Redis 分钟桶）+ Token TPM/TPD 预检 — 超出抛 RATE_001"""
    tenant_id = state["tenant_id"]
    if not check_rate_limit(tenant_id):
        state["finish_reason"] = "rate_limited"
        state["error_code"] = "RATE_001"
        state["response"] = "请求过于频繁，请稍后再试。"
        raise NexusAIException("RATE_001", "rate_limited")

    estimated = estimate_request_tokens(state)
    if not check_token_quota(tenant_id, estimated):
        state["finish_reason"] = "rate_limited"
        state["error_code"] = "RATE_001"
        state["response"] = "请求过于频繁，请稍后再试。"
        raise NexusAIException("RATE_001", "token_quota_exceeded")
    return state
