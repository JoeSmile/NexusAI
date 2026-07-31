"""断路器模块测试"""

import pytest

from backend.core.circuit_breaker import CircuitBreaker


@pytest.mark.asyncio
async def test_initial_state():
    cb = CircuitBreaker()
    assert cb.state.value == "closed"


@pytest.mark.asyncio
async def test_open_on_failures():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)

    async def fail():
        raise Exception("fail")

    for _ in range(2):
        try:
            await cb.call(fail)
        except Exception:
            pass

    assert cb.state.value == "open"
