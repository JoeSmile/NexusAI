"""Harness 模块测试"""

import pytest

from backend.core.harness import Harness


@pytest.mark.asyncio
async def test_harness_success():
    h = Harness("test")

    async def ok():
        return "hello"

    result = await h.wrap(
        fn=ok, type="test", name="test_fn", tenant_id="t1", input=None
    )
    assert result.success
    assert result.output == "hello"
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_harness_timeout():
    h = Harness("test_timeout")

    async def slow():
        import asyncio

        await asyncio.sleep(10)
        return "too slow"

    result = await h.wrap(
        fn=slow,
        type="test",
        name="slow_fn",
        tenant_id="t1",
        input=None,
        metadata={"timeout": 0.1, "fallback": "fallback"},
    )
    assert not result.success
    assert result.error == "timeout"
    assert result.output == "fallback"
