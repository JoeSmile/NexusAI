"""断路器 — closed → (失败 N 次) → open → (超时) → half-open → (成功 1 次) → closed"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Any, Callable


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"


class CircuitBreaker:
    """断路器"""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        name: str = "default",
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time > self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
        return self._state

    async def call(self, fn: Callable, fallback_fn: Callable | None = None) -> Any:
        """执行被保护函数"""
        if self.state == CircuitState.OPEN:
            if fallback_fn:
                if asyncio.iscoroutinefunction(fallback_fn):
                    return await fallback_fn()
                return fallback_fn()
            raise Exception(f"CircuitBreaker[{self.name}]: open")

        try:
            if asyncio.iscoroutinefunction(fn):
                result = await fn()
            else:
                result = fn()
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            if fallback_fn:
                if asyncio.iscoroutinefunction(fallback_fn):
                    return await fallback_fn()
                return fallback_fn()
            raise

    def _on_success(self) -> None:
        self._failure_count = 0
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED

    def _on_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
