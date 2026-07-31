"""速率限制 — 桶令牌（租户级）"""

from __future__ import annotations

import time
from collections import defaultdict


class TokenBucket:
    """租户级桶令牌速率限制器"""

    def __init__(self, rate: float = 10.0, burst: int = 20):
        self.rate = rate
        self.burst = burst
        self._tokens: dict[str, float] = defaultdict(lambda: float(burst))
        self._last_refill: dict[str, float] = defaultdict(time.time)

    def consume(self, tenant_id: str) -> bool:
        """消费一个 token，返回是否允许通过"""
        now = time.time()
        elapsed = now - self._last_refill[tenant_id]
        self._tokens[tenant_id] = min(
            self.burst,
            self._tokens[tenant_id] + elapsed * self.rate,
        )
        self._last_refill[tenant_id] = now
        if self._tokens[tenant_id] >= 1:
            self._tokens[tenant_id] -= 1
            return True
        return False

    def reset(self, tenant_id: str) -> None:
        """重置租户的桶"""
        self._tokens[tenant_id] = float(self.burst)
        self._last_refill[tenant_id] = time.time()


_bucket = TokenBucket()


def check_rate_limit(tenant_id: str) -> bool:
    """检查是否被限流"""
    return _bucket.consume(tenant_id)
