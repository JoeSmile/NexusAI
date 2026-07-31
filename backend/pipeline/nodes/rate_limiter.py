"""速率限制节点 — 桶令牌检查"""

from __future__ import annotations

import time
from collections import defaultdict

from backend.core.errors import ContextGateException
from backend.pipeline.state import PipelineState


class TokenBucket:
    """租户级桶令牌"""

    def __init__(self, rate: float = 10.0, burst: int = 20):
        self.rate = rate
        self.burst = burst
        self.tokens: dict[str, float] = defaultdict(lambda: float(burst))
        self.last_refill: dict[str, float] = defaultdict(time.time)

    def consume(self, tenant_id: str) -> bool:
        now = time.time()
        elapsed = now - self.last_refill[tenant_id]
        self.tokens[tenant_id] = min(
            self.burst,
            self.tokens[tenant_id] + elapsed * self.rate,
        )
        self.last_refill[tenant_id] = now
        if self.tokens[tenant_id] >= 1:
            self.tokens[tenant_id] -= 1
            return True
        return False


_bucket = TokenBucket()


async def rate_limiter(state: PipelineState) -> PipelineState:
    """桶令牌检查 — 超出抛 RATE_001"""
    if not _bucket.consume(state["tenant_id"]):
        state["finish_reason"] = "rate_limited"
        state["error_code"] = "RATE_001"
        state["response"] = "请求过于频繁，请稍后再试。"
        raise ContextGateException("RATE_001", "rate_limited")
    return state
