"""通用 Harness — 断路器 + 重试退避 + 超时 + 计时 + 错误分类"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from backend.core.circuit_breaker import CircuitBreaker
from backend.core.metrics import errors_total


@dataclass
class HarnessResult:
    """Harness 执行结果"""

    output: Any = None
    type: str = ""
    name: str = ""
    latency_ms: float = 0.0
    success: bool = True
    error: str | None = None
    metadata: dict = field(default_factory=dict)


class Harness:
    """通用调用 wrapper"""

    def __init__(self, name: str = "default"):
        self.name = name
        self._breaker = CircuitBreaker(
            name=name, failure_threshold=5, recovery_timeout=30
        )

    async def wrap(
        self,
        fn: Callable[[], Awaitable[Any]],
        *,
        type: str,
        name: str,
        tenant_id: str,
        input: Any,
        metadata: dict | None = None,
    ) -> HarnessResult:
        meta = metadata or {}
        start = time.time()

        async def _protected():
            return await self._breaker.call(fn=fn)

        try:
            output = await asyncio.wait_for(
                self._retry(_protected),
                timeout=float(meta.get("timeout", 30)),
            )
        except TimeoutError:
            self._record_error(tenant_id, type, name, "timeout")
            return HarnessResult(
                output=meta.get("fallback", ""),
                type=type,
                name=name,
                success=False,
                error="timeout",
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            self._record_error(tenant_id, type, name, str(e))
            raise

        latency = (time.time() - start) * 1000
        self._record_metrics(type, name, latency)
        return HarnessResult(
            output=output,
            type=type,
            name=name,
            latency_ms=latency,
            success=True,
            metadata=meta,
        )

    async def _retry(self, fn: Callable[[], Awaitable[Any]]) -> Any:
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                return await fn()
            except Exception as e:
                last_exc = e
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
        assert last_exc is not None
        raise last_exc

    def _record_error(
        self, tenant_id: str, type: str, name: str, reason: str
    ) -> None:
        errors_total.labels(tenant=tenant_id, error_code=f"{type}.{reason}"[:64]).inc()

    def _record_metrics(self, type: str, name: str, latency_ms: float) -> None:
        from backend.core.metrics import request_duration

        request_duration.labels(
            method=type, endpoint=name, status="2xx"
        ).observe(latency_ms)
