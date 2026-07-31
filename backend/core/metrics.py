"""Prometheus 指标定义"""

from __future__ import annotations

import time

from fastapi import Request, Response
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware

# ── 请求指标 ──
request_duration = Histogram(
    "contextgate_request_duration_ms",
    "Request latency in milliseconds",
    labelnames=["method", "endpoint", "status"],
    buckets=[5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000],
)

requests_total = Counter(
    "contextgate_requests_total",
    "Total requests",
    labelnames=["tenant", "status"],
)

# ── Token 指标 ──
tokens_total = Counter(
    "contextgate_tokens_total",
    "Total tokens consumed",
    labelnames=["tenant", "model"],
)

# ── 缓存指标 ──
cache_hits = Counter(
    "contextgate_cache_hits_total",
    "Total cache hits",
    labelnames=["tenant", "cache_type"],
)

cache_misses = Counter(
    "contextgate_cache_misses_total",
    "Total cache misses",
    labelnames=["tenant"],
)

# ── 护栏指标 ──
guardrails_blocked = Counter(
    "contextgate_guardrails_blocked_total",
    "Total blocked by guardrails",
    labelnames=["tenant", "guard"],
)

# ── 成本指标 ──
cost_total = Counter(
    "contextgate_cost_total",
    "Total cost in USD",
    labelnames=["tenant", "model"],
)

# ── 错误指标 ──
errors_total = Counter(
    "contextgate_errors_total",
    "Total errors by code",
    labelnames=["tenant", "error_code"],
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """自动记录请求指标"""

    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response: Response = await call_next(request)
        latency = (time.time() - start) * 1000
        status_group = f"{response.status_code // 100}xx"
        endpoint = request.url.path
        request_duration.labels(
            method=request.method, endpoint=endpoint, status=status_group
        ).observe(latency)
        tenant_context = getattr(request.state, "tenant_context", None)
        tenant = (
            tenant_context.tenant_id
            if tenant_context is not None
            else getattr(request.state, "tenant_id", "unknown")
        )
        requests_total.labels(tenant=tenant, status=status_group).inc()
        return response
